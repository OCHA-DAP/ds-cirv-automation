from pathlib import Path
from datetime import datetime, timezone
from io import BytesIO
import json, re

import numpy as np
import pandas as pd
import pymupdf
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
RAW = PROJECT / 'data' / 'raw' / 'iasc' / 'horizon'
PROCESSED = PROJECT / 'data' / 'processed'
CONFIG = PROJECT / 'config'
RAW.mkdir(parents=True, exist_ok=True); PROCESSED.mkdir(parents=True, exist_ok=True)
COUNTRIES_FILE = CONFIG / 'countries.csv'
CURRENT_OUTPUT = PROJECT / 'iasc_horizon_current.csv'
EVIDENCE_OUTPUT = PROCESSED / 'iasc_horizon_evidence.csv'
UNMATCHED_OUTPUT = PROCESSED / 'iasc_horizon_unmatched.csv'
METADATA_OUTPUT = PROCESSED / 'iasc_horizon_metadata.json'
EXPECTED_COUNTRIES = 150

MATRIX = {
    1:{1:1,2:1,3:2,4:2,5:2}, 2:{1:1,2:2,3:2,4:3,5:3},
    3:{1:2,2:2,3:3,4:3,5:4}, 4:{1:2,2:3,3:3,4:4,5:4},
    5:{1:2,2:3,3:4,4:4,5:5},
}
LEVEL_RESULT = {1:('Low',0.0),2:('Low',0.0),3:('Moderate',33.0),4:('High',67.0),5:('Very High',100.0)}
SERIOUSNESS = {'very low':(1,'Low',0.0),'low':(2,'Low',0.0),'moderate':(3,'Moderate',33.0),'high':(4,'High',67.0),'very high':(5,'Very High',100.0)}

REGIONAL_MAP = {
    'afghanistan pakistan':['AFG','PAK'], 'eritrea ethiopia':['ERI','ETH'],
    'drc and great lakes':['COD'], 'lake chad basin':['CMR','TCD','NER','NGA'],
    'central sahel':['BFA','MLI','NER'], 'syria (north)':['SYR'],
}
SPECIAL = {'drc':'COD','democratic republic of congo':'COD','democratic republic of the congo':'COD','south sudan':'SSD'}


def norm(v):
    return ' '.join(
        str(v or '')
        .strip()
        .lower()
        .replace("\\n", " ")
        .replace("–", "-")
        .replace("—", "-")
        .replace("&", " and ")
        .replace("/", " ")
        .replace("-", " ")
        .split()
    )


def clean_source_label(value):
    if value is None or pd.isna(value):
        return value

    text = re.sub(
        r"\\s+",
        " ",
        str(value).replace("\\n", " "),
    ).strip()

    text = re.sub(
        r"\\s*&\\s*",
        " & ",
        text,
    )

    text = re.sub(
        r"\\s+-\\s+",
        " - ",
        text,
    )

    return text

def iso3(v):
    s=str(v or '').strip().upper(); return s if len(s)==3 and s.isalpha() else None

def load_universe():
    df=pd.read_csv(COUNTRIES_FILE,encoding='utf-8-sig',low_memory=False)
    df['ISO3']=df['ISO3'].apply(iso3)
    df=df[df.ISO3.notna()][['ISO3','CERF_Country']].drop_duplicates('ISO3').reset_index(drop=True)
    if len(df)!=EXPECTED_COUNTRIES: raise RuntimeError(f'Country universe has {len(df)} rows; expected {EXPECTED_COUNTRIES}.')
    return df

def aliases(universe):
    out={norm(r.CERF_Country):r.ISO3 for _,r in universe.iterrows()}; out.update({norm(k):v for k,v in SPECIAL.items()}); return out

def map_label(label, lookup):
    key=norm(label)
    if key in REGIONAL_MAP: return REGIONAL_MAP[key]
    if key in lookup: return [lookup[key]]
    candidates=[(len(a),i) for a,i in lookup.items() if re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)',key)]
    return [max(candidates)[1]] if candidates else []

def find_pdf():
    files=list(RAW.glob('*.pdf'))+list(PROJECT.glob('*Early Warning*Brief*.pdf'))+list(PROJECT.glob('*Horizon*Scan*.pdf'))
    files=list({str(p.resolve()).lower():p for p in files}.values())
    if not files: raise FileNotFoundError('No Early Warning Brief PDF found.')
    return max(files,key=lambda p:p.stat().st_mtime)

# ---- Profile badges: NO OCR. Read original embedded badge image object. ----
def badge_image(page, doc):
    choices=[]
    for info in page.get_images(full=True):
        xref=info[0]; raw=doc.extract_image(xref); im=Image.open(BytesIO(raw['image'])).convert('RGB')
        w,h=im.size
        # profile badge is wide; logo is square
        if w/h >= 2.2 and w >= 250 and h >= 70: choices.append((w*h,im,xref))
    if not choices: return None,None
    _,im,xref=max(choices,key=lambda x:x[0]); return im,xref

def gauge_level(half):
    """Decode tested gauge encodings from arc geometry and colour, never OCR.

    Only the encodings verified in this document (Low, High, Very High)
    are accepted. Unknown graphics return None rather than a guessed level.
    """
    import cv2
    a=np.asarray(half.convert('RGB')); h,w,_=a.shape
    hsv=cv2.cvtColor(a,cv2.COLOR_RGB2HSV)
    neutral=(a.max(2)-a.min(2)<20)&(a.mean(2)>60)&(a.mean(2)<170)
    mask=(((hsv[:,:,1]>80)&(hsv[:,:,2]>80))|neutral).astype('uint8')
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    choices=[]
    for i,st in enumerate(stats):
        if i and st[2]>.25*w and st[3]>.30*h:
            choices.append((st[4],i))
    if not choices: return None,None
    _,i=max(choices); yy,xx=np.where(labels==i)
    # Full red semicircle, three-quarter orange arc, half grey arc.
    # Width/height provides an independent geometric check of colour.
    st=stats[i]; span=float(st[2]/st[3])
    r,g,b=np.median(a[labels==i],axis=0)
    if r>150 and g<65 and b<100 and 1.75<span<2.30: return 5,span
    if r>180 and 65<g<160 and b<80 and 1.45<span<1.85: return 4,span
    if max(r,g,b)-min(r,g,b)<20 and .85<span<1.20: return 2,span
    return None,span

def profile_records(doc, lookup, source_name):
    # Discover profile names from page 2 list, then pair in order with pages until Risk Tracker.
    page2=doc[1].get_text('text') if len(doc)>1 else ''
    names=[]
    for line in page2.splitlines():
        m=re.match(r'^\s*([A-Za-z][A-Za-z .-]+):\s*',line)
        if m and map_label(m.group(1),lookup): names.append(m.group(1).strip())
    # stable unique; expected Yemen, South Sudan, Myanmar in this brief
    names=list(dict.fromkeys(names))
    profile_pages=[]
    for idx in range(2,len(doc)):
        if 'risk tracker' in norm(doc[idx].get_text('text')): break
        profile_pages.append(idx)
    if len(names)!=len(profile_pages):
        raise RuntimeError('Profile list and profile page count disagree; refusing positional country assignment.')

    recs=[]; unmatched=[]
    for idx,label in zip(profile_pages,names):
        im,xref=badge_image(doc[idx],doc)
        if im is None:
            unmatched.append({'Source_Label':label,'Section':'Risks of High Concern','PDF_Page':idx+1,'Reason':'No embedded badge image found'})
            continue
        w,h=im.size
        left=im.crop((0,0,int(w*0.44),h)); right=im.crop((int(w*0.56),0,w,h))
        likelihood,lratio=gauge_level(left); impact,iratio=gauge_level(right)
        if likelihood is None or impact is None:
            unmatched.append({'Source_Label':label,'Section':'Risks of High Concern','PDF_Page':idx+1,'Reason':'Badge image found but gauge fill could not be classified'})
            continue
        matrix=MATRIX[impact][likelihood]; seriousness,score=LEVEL_RESULT[matrix]
        mapped=map_label(label,lookup)
        if not mapped:
            unmatched.append({'Source_Label':label,'Section':'Risks of High Concern','PDF_Page':idx+1,'Reason':'Profile country could not be mapped'})
            continue
        evidence=f'Embedded image xref={xref}; likelihood arc aspect={lratio:.3f}->level {likelihood}; impact arc aspect={iratio:.3f}->level {impact}'
        for code in mapped:
            recs.append({'ISO3':code,'Source_Label':label,'IASC_Early_Warning_Impact_Level':impact,'IASC_Early_Warning_Likelihood_Level':likelihood,'IASC_Early_Warning_Matrix_Level':matrix,'IASC_Early_Warning_Seriousness':seriousness,'IASC_Early_Warning_Type':pd.NA,'IASC_Early_Warning_Score':score,'IASC_Scoring_Method':'Embedded badge image gauge geometry + Impact x Likelihood matrix','IASC_Source_Section':'Risks of High Concern','IASC_PDF_Page':idx+1,'IASC_Rating_Evidence':evidence,'IASC_Source_File':source_name})
        print(f'Profile {label}: Likelihood={likelihood} ({lratio:.3f}), Impact={impact} ({iratio:.3f}), Matrix={matrix}, Score={score:g}')
    return recs,unmatched

# ---- Risk Tracker: extract actual PDF TABLE CELLS with PyMuPDF find_tables(). ----
def tracker_records(doc, lookup, source_name):
    recs=[]; unmatched=[]
    current_region=None; current_country=None
    for idx,page in enumerate(doc):
        text=norm(page.get_text('text'))
        if 'risk tracker' not in text or 'seriousness' not in text: continue
        tables=page.find_tables().tables
        for table in tables:
            rows=table.extract()
            if not rows: continue
            # locate header row, normalize columns
            header_idx=None
            for n,row in enumerate(rows):
                cells=[norm(c) for c in row]
                if 'country' in cells and 'seriousness' in cells and 'status' in cells:
                    header_idx=n; header=cells; break
            if header_idx is None: continue
            col={name:i for i,name in enumerate(header)}
            for row_number,row in enumerate(rows[header_idx+1:],start=header_idx+1):
                if len(row)<len(header): continue
                if not row[col['status']] and row[0] and 'active' in norm(row[0]):
                    # Repair an unruled bottom row using header column boundaries.
                    box=next((c for c in table.rows[row_number].cells if c),None)
                    header_cells=table.rows[header_idx].cells
                    if box and all(header_cells):
                        row=[page.get_text('text',clip=pymupdf.Rect(c[0],box[1],c[2],box[3])).strip() for c in header_cells]
                region=(row[col.get('region',0)] or '').strip() if col.get('region') is not None else ''
                country=(row[col['country']] or '').strip()
                status=(row[col['status']] or '').strip()
                seriousness_raw=(row[col['seriousness']] or '').strip()
                risk_type=(row[col.get('risk type',0)] or '').strip() if 'risk type' in col else ''
                risk_title=(row[col.get('risk title',0)] or '').strip() if 'risk title' in col else ''
                month=(row[col.get('month',0)] or '').strip() if 'month' in col else ''
                if region: current_region=region
                if country: current_country=country
                elif current_country and month: country=current_country  # multi-row country e.g. Nigeria
                if norm(status)!='active' or norm(seriousness_raw) not in SERIOUSNESS: continue
                level,seriousness,score=SERIOUSNESS[norm(seriousness_raw)]
                mapped=map_label(country,lookup)
                country = clean_source_label(country)
                risk_type = clean_source_label(risk_type)
                risk_title = clean_source_label(risk_title)

                base={'Source_Label':country,'IASC_Early_Warning_Impact_Level':pd.NA,'IASC_Early_Warning_Likelihood_Level':pd.NA,'IASC_Early_Warning_Matrix_Level':level,'IASC_Early_Warning_Seriousness':seriousness,'IASC_Early_Warning_Type':re.sub(r'\s+',' ',risk_type.replace('\n','; ')).strip(),'IASC_Early_Warning_Score':score,'IASC_Scoring_Method':'Structured Risk Tracker table Seriousness field','IASC_Source_Section':'Risk Tracker','IASC_PDF_Page':idx+1,'IASC_Rating_Evidence':f'Region={current_region}; Country={country}; Month={month}; Status={status}; Seriousness={seriousness_raw}; Risk={risk_title}','IASC_Source_File':source_name}
                if mapped:
                    for code in mapped: recs.append({'ISO3':code,**base})
                else:
                    # Keep global/regional rows in evidence even though they cannot be assigned to ISO3.
                    recs.append({'ISO3':pd.NA,**base})
    return recs,unmatched

def consolidate(group):
    g=group.copy(); g['IASC_Early_Warning_Score']=pd.to_numeric(g['IASC_Early_Warning_Score'],errors='coerce')
    best=g.IASC_Early_Warning_Score.max(); s=g[g.IASC_Early_Warning_Score.eq(best)]
    def join(col):
        vals=[]
        for v in s[col].dropna():
            for p in str(v).split(';'):
                p=p.strip()
                if p and p not in vals: vals.append(p)
        return '; '.join(vals) if vals else pd.NA
    levels=pd.to_numeric(s.IASC_Early_Warning_Matrix_Level,errors='coerce').dropna()
    return pd.Series({'IASC_Early_Warning_Impact_Level':s.iloc[0].get('IASC_Early_Warning_Impact_Level',pd.NA),'IASC_Early_Warning_Likelihood_Level':s.iloc[0].get('IASC_Early_Warning_Likelihood_Level',pd.NA),'IASC_Early_Warning_Matrix_Level':int(levels.max()) if not levels.empty else pd.NA,'IASC_Early_Warning_Seriousness':s.iloc[0].IASC_Early_Warning_Seriousness,'IASC_Early_Warning_Type':join('IASC_Early_Warning_Type'),'IASC_Early_Warning_Score':float(best),'IASC_Horizon_Listed':True,'IASC_Horizon_Source_Labels':join('Source_Label'),'IASC_Horizon_Source_Sections':join('IASC_Source_Section'),'IASC_Horizon_Scoring_Methods':join('IASC_Scoring_Method')})

def update_iasc_horizon():
    source=find_pdf(); print(f'Loading IASC Brief:\n{source}')
    universe=load_universe(); lookup=aliases(universe); doc=pymupdf.open(str(source))
    profiles,pbad=profile_records(doc,lookup,source.name); tracker,tbad=tracker_records(doc,lookup,source.name)
    evidence=pd.DataFrame(profiles+tracker); unmatched=pd.DataFrame(pbad+tbad)
    if pbad or tbad:
        unmatched.to_csv(UNMATCHED_OUTPUT,index=False,encoding='utf-8-sig')
        raise RuntimeError('Extraction incomplete; current country output was not overwritten. See unmatched CSV.')
    country_evidence=evidence[evidence.ISO3.notna()].copy()
    if country_evidence.empty: raise RuntimeError('No country-level IASC evidence parsed.')
    summary=country_evidence.groupby('ISO3',group_keys=False).apply(consolidate).reset_index()
    current=universe.merge(summary,on='ISO3',how='left'); current['IASC_Horizon_Listed']=current['IASC_Horizon_Listed'].fillna(False); current['IASC_Horizon_Source_File']=source.name
    date_match=re.search(r'Released:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})',doc[0].get_text())
    current['IASC_Horizon_Brief_Date']=pd.to_datetime(date_match.group(1),errors='coerce').strftime('%Y-%m-%d') if date_match else None
    if len(current)!=len(universe) or current.ISO3.duplicated().any(): raise RuntimeError('150-country validation failed.')
    current.to_csv(CURRENT_OUTPUT,index=False,encoding='utf-8-sig'); evidence.to_csv(EVIDENCE_OUTPUT,index=False,encoding='utf-8-sig'); unmatched.to_csv(UNMATCHED_OUTPUT,index=False,encoding='utf-8-sig')
    meta={'source':source.name,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'decoder_scope':'Tested Low/High/Very High gauge encodings; unknown encodings are flagged, never guessed','profile_method':'Direct embedded badge-image extraction; gauge fill geometry; no OCR','tracker_method':'PyMuPDF structured table extraction; explicit Seriousness field','matrix':MATRIX,'listed_countries':int(current.IASC_Horizon_Listed.sum()),'evidence_records':len(evidence),'unmatched_records':len(unmatched)}
    METADATA_OUTPUT.write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('\nIASC HORIZON VALIDATION PASSED'); print('Countries in output:',len(current)); print('Countries with Early Warning signals:',int(current.IASC_Horizon_Listed.sum())); print('Unmatched/uncertain records:',len(unmatched))
    return current

if __name__=='__main__':
    df=update_iasc_horizon(); print('\n'+'='*70+'\nIASC HORIZON UPDATE COMPLETE\n'+'='*70)
    show=df[df.IASC_Horizon_Listed].copy(); cols=['CERF_Country','ISO3','IASC_Early_Warning_Impact_Level','IASC_Early_Warning_Likelihood_Level','IASC_Early_Warning_Matrix_Level','IASC_Early_Warning_Seriousness','IASC_Early_Warning_Score','IASC_Horizon_Source_Labels','IASC_Horizon_Scoring_Methods']; print(show[cols].sort_values(['IASC_Early_Warning_Score','CERF_Country'],ascending=[False,True]).to_string(index=False))
