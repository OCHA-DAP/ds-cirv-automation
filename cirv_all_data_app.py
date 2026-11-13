from datetime import datetime
from cirv_refresh_ui import refresh_controls
"""CIRV integration based on the actual uploaded collector audit. No fuzzy discovery."""
from pathlib import Path
from un_page_icon import get_page_icon
from io import BytesIO
import json, re, math, html, zipfile, posixpath
from lxml import etree as ET
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

ROOT=Path(__file__).resolve().parent
SHEET='CERF UFE 2026-I All Data'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
# lxml preserves original namespace declarations and workbook extensions.
# Exact files and columns observed in cirv_integration_audit.json.
REGISTRY={
 'risk':('inform_risk_current.csv',['INFORM_Risk_Raw']),
 'severity':('inform_severity_current.csv',['INFORM_Severity_Raw']),
 'food':('food_security_current.csv',['ipc_value','fewsnet_value','grfc_value','IPC_Classification','fao_value','asap_value','sofi_value','CERF_Food_Insecurity']),
 'conflict':('conflict_current.csv',['ACLED_WCI_Normalized','ACLED_Trends_Score','CrisisWatch_Score','CERF_Conflict_Consolidated']),
 'iasc':('iasc_current.csv',['CERF_IASC_Consolidated','IASC_Early_Warning_Seriousness']),
 'hdx':('hdx_ipc_update_comparison.csv',['New_HDX_IPC']),
 'fews':('fewsnet_faob_current.csv',['FEWSNET_IPC']),
 'grfc':('grfc_current.csv',['GRFC_Phase','GRFC_Category']),
 'fao':('fao_crop_prospects_current.csv',['FAO_Score','FAO_Category']),
 'asap':('asap_hotspots_current.csv',['ASAP_Hotspot']),
 'sofi':('sofi_current.csv',['SOFI_Score','SOFI_Period']),
 'wci':('acled_wci_current.csv',['ACLED_WCI']),
 'trends':('acled_trends_current.csv',['ACLED_Trends_Percent']),
 'crisiswatch':('crisiswatch_current.csv',['CrisisWatch_Months_In_Window']),
 'horizon':('iasc_horizon_current.csv',['IASC_Early_Warning_Score']),
 'scaleup':('iasc_scaleup_current.csv',['IASC_ScaleUp_Active']),
}
PRIMARY=['risk','severity','food','conflict','iasc']
VISIBLE=[c for c in range(1,29) if c not in (3,9,14)]
NUMERIC=[4,5,6,7,10,11,12,13,15,16,18,19,20,21,22,23,24,25,26,27,28]


def reference(root=ROOT):
 files=list(root.glob('260810*CERF*UFE*2026-I*CIRV*.xlsx'))
 p=root/'config'/'cirv_template.xlsx'
 if p.exists():files.append(p)
 if not files:raise FileNotFoundError('Put the August reference workbook in the project root (or config/cirv_template.xlsx).')
 return files[0]


def template_data(path):
 wb=load_workbook(path,data_only=True,read_only=False)
 ws=wb[SHEET]
 rows=[r for r in range(5,ws.max_row+1) if re.fullmatch('[A-Z]{3}',str(ws.cell(r,2).value or ''))]
 if len(rows)!=150:raise ValueError(f'Reference country universe is {len(rows)}, not 150.')
 headers={c:str(ws.cell(3,c).value or ('CERF- Multi-Indicator Consolidated' if c==25 else '')) for c in range(1,29)}
 headers[1]=headers[1].strip()
 headers[13]="Global Report on Food Crises 2026 (0-5)"
 data=pd.DataFrame([[ws.cell(r,c).value for c in range(1,29)] for r in rows],columns=range(1,29))
 data.index=data[2].astype(str);data.index.name='ISO3'
 return wb,rows,headers,data


def food_formula(o,p,r,s):
 num=den=0.0
 if pd.notna(o) and o>0:num+=o*.6;den+=.6
 if (pd.notna(p) and p>0) or (pd.notna(r) and r>0):
  den+=.2
  if pd.notna(p) and p>0 and pd.notna(r) and r>0:num+=p*2.5*.1+r*2.5*.1
  elif pd.notna(p) and p>0:num+=p*2.5*.2
  else:num+=r*2.5*.2
 if pd.notna(s) and s>0:num+=s/20*.2;den+=.2
 return num*20/den if den else 0.0


def compute(data, use_processor_food=True):
 d=data.copy()
 for c in NUMERIC:d[c]=pd.to_numeric(d[c],errors='coerce')
 # Raw 0-10 scores are multiplied ONCE. Never clip bad source scales into 100.
 d[5]=d[4]*10;d[7]=d[6]*10
 if not use_processor_food:d[20]=[food_formula(*v) for v in d[[15,16,18,19]].itertuples(index=False,name=None)]
 d[24]=(d[22]+(d[23].fillna(50)-50)*.2+(d[21].fillna(50)-50)*.2).clip(0,100)
 d[25]=d[10].fillna(0)*5/33+d[20]*13/33+d[24]*15/33
 d[26]=d[5]*.5+d[25]*.5;d[27]=d[5]/3+d[7]/3+d[25]/3
 d[28]=d[27].where(d[6].fillna(0)>0,d[26])
 return d


def parity(path):
 _,_,_,d=template_data(path)
 # Actual source workbook has row-specific legacy formulas; compare standard formula rows separately.
 formulas=load_workbook(path,data_only=False)[SHEET]
 calc=compute(d,False);result=[]
 for c in [5,7,20,24,25,26,27,28]:
  dif=(pd.to_numeric(calc[c],errors='coerce')-pd.to_numeric(d[c],errors='coerce')).abs()
  for iso in d.index[dif.gt(1e-6)]:
   r=5+list(d.index).index(iso)
   result.append({'ISO3':iso,'column':c,'formula':formulas.cell(r,c).value,'cached_reference':d.loc[iso,c],'standard_calculation':calc.loc[iso,c]})
 return result


def load_sources(root=ROOT):
 sources={};status=[];errors=[]
 for key,(filename,columns) in REGISTRY.items():
  paths=[root/filename,root/'data'/'processed'/filename]
  p=next((p for p in paths if p.exists()),None)
  if p is None:
   status.append({'source':key,'file':filename,'status':'MISSING','rows':0})
   if key in REGISTRY:errors.append(f'{key}: missing {filename}')
   continue
  try:
   df=pd.read_csv(p,encoding='utf-8-sig',low_memory=False)
   missing=[c for c in ['ISO3']+columns if c not in df]
   if missing:raise ValueError('missing columns '+', '.join(missing))
   df['ISO3']=df['ISO3'].astype(str).str.upper().str.strip()
   if df['ISO3'].duplicated().any():raise ValueError('duplicate ISO3 rows')
   sources[key]=df.set_index('ISO3',drop=False)
   status.append({'source':key,'file':str(p.relative_to(root)),'status':'LOADED','rows':len(df)})
  except Exception as exc:
   status.append({'source':key,'file':filename,'status':str(exc),'rows':0})
   if key in REGISTRY:errors.append(f'{key}: {exc}')
 return sources,pd.DataFrame(status),errors



def _dynamic_fao_titles(headers, sources):
    import calendar
    months = list(calendar.month_name)[1:]
    month_pattern = (
        r"January|February|March|April|May|June|July|August|"
        r"September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    )

    def parse_period(value):
        value = str(value).strip()
        match = re.search(
            r"\b(" + month_pattern + r")\.?[\s,/_-]+(20\d{2})\b",
            value, re.I
        )
        if match:
            month = next(
                m for m in months
                if m.lower().startswith(match.group(1).lower()[:3])
            )
            return month + " " + match.group(2)
        match = re.fullmatch(
            r"(20\d{2})[-/](0?[1-9]|1[0-2])"
            r"(?:[-/]\d{1,2})?(?:[ T].*)?", value
        )
        if match:
            return months[int(match.group(2)) - 1] + " " + match.group(1)
        return None

    period = None
    frame = sources.get("fao")
    fields = {
        "report_period", "report_date", "report_month",
        "publication_date", "publication_month",
        "reference_period", "fao_period", "fao_report_date",
        "fao_report_period", "source_period",
        "report_title", "source_title"
    }
    if frame is not None:
        for column in frame.columns:
            key = re.sub(
                r"[^a-z0-9]+", "_", str(column).lower()
            ).strip("_")
            if key not in fields:
                continue
            periods = {
                parse_period(v) for v in frame[column].dropna().unique()
            }
            periods.discard(None)
            if len(periods) == 1:
                period = periods.pop()
                break

    for column, title in list(headers.items()):
        if column not in (16, 17) and not re.search(
            r"FAO.*Crop Prospects", str(title), re.I
        ):
            continue
        cleaned = re.sub(
            r"\s*\[(?:report period unavailable|"
            + month_pattern + r"\s+20\d{2})\]",
            "", str(title), flags=re.I
        )
        cleaned = re.sub(
            r"\(\s*(?:" + month_pattern
            + r")\.?\s*[,/-]?\s*20\d{2}\s*\)",
            "", cleaned, flags=re.I
        )
        cleaned = re.sub(
            r"\b(?:" + month_pattern
            + r")\.?\s*[,/-]?\s*20\d{2}\b",
            "", cleaned, flags=re.I
        )
        cleaned = cleaned.replace("(report period unavailable)", "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,:")
        headers[column] = cleaned + (
            f" ({period})" if period
            else " (report period unavailable)"
        )
    return headers


# DYNAMIC_ASAP_PATCH
def update_asap_heading(headers, sources):
    frame = sources.get("asap")
    if frame is None or "ASAP_Date" not in frame.columns:
        headers[18] = (
            "ASAP Agricultural Production Hotspots "
            "(assessment period unavailable)"
        )
        return headers

    dates = pd.to_datetime(
        frame["ASAP_Date"],
        errors="coerce",
    ).dropna()

    if dates.empty:
        headers[18] = (
            "ASAP Agricultural Production Hotspots "
            "(assessment period unavailable)"
        )
        return headers

    latest = dates.max()
    headers[18] = latest.strftime(
        "ASAP Agricultural Production Hotspots (%B %Y)"
    )
    return headers


# DYNAMIC_HDX_IPC_HEADING
def update_hdx_ipc_heading(headers, root=ROOT):
    candidates = [
        root / "food_security_current.csv",
        root / "data" / "processed" / "food_security_current.csv",
    ]

    source = next(
        (path for path in candidates if path.exists()),
        None,
    )

    if source is None:
        headers[11] = (
            "HDX IPC current analyses "
            "(rolling 12-month window)"
        )
        return headers

    refreshed = datetime.fromtimestamp(
        source.stat().st_mtime
    )

    headers[11] = (
        f"HDX IPC (as of {refreshed.strftime('%d/%m/%Y')})"
    )

    return headers


# DYNAMIC_SOFI_HEADING
def update_sofi_heading(headers, sources):
    frame = sources.get("sofi")

    if frame is None:
        headers[19] = "SOFI (period unavailable)"
        return headers

    # Prefer the reporting-period field produced by the SOFI collector.
    period_col = next(
        (
            c for c in frame.columns
            if str(c).lower() in (
                "sofi_period",
                "report_period",
                "reporting_period",
                "period",
            )
        ),
        None,
    )

    if period_col is None:
        headers[19] = "SOFI (period unavailable)"
        return headers

    periods = (
        frame[period_col]
        .dropna()
        .astype(str)
        .str.strip()
    )
    periods = periods[periods.ne("")].unique()

    if len(periods) != 1:
        headers[19] = "SOFI (period unavailable)"
        return headers

    period = periods[0].replace("_", "-")

    headers[19] = f"SOFI ({period})"
    return headers


# DYNAMIC_FAOB_HEADING
def update_faob_heading(headers, sources):
    frame = sources.get("fews")

    if frame is None or "Report_Period" not in frame.columns:
        headers[12] = "FEWS NET FAOB (period unavailable)"
        return headers

    periods = (
        frame["Report_Period"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    periods = periods[periods.ne("")].unique()

    if len(periods) != 1:
        headers[12] = "FEWS NET FAOB (period unavailable)"
        return headers

    headers[12] = f"FEWS NET FAOB ({periods[0]})"
    return headers

def assemble(path,root=ROOT):
 wb,rows,headers,baseline=template_data(path)
 src,status,errors=load_sources(root)
 headers=update_faob_heading(headers,src)
 headers=update_sofi_heading(headers,src)
 headers=update_hdx_ipc_heading(headers,root)
 headers=update_asap_heading(headers,src)
 headers=_dynamic_fao_titles(headers,src)
 d=pd.DataFrame(index=baseline.index,columns=range(1,29));d[1]=baseline[1];d[2]=baseline[2]
 def assign(key,column,target):
  if key in src:d[target]=src[key][column].reindex(d.index)
 assign('risk','INFORM_Risk_Raw',4);assign('severity','INFORM_Severity_Raw',6)
 assign('iasc','IASC_Early_Warning_Seriousness',8);assign('iasc','CERF_IASC_Consolidated',10)
 for col,target in [('ipc_value',11),('fewsnet_value',12),('grfc_value',13),('IPC_Classification',15),('fao_value',16),('asap_value',18),('sofi_value',19),('CERF_Food_Insecurity',20)]:assign('food',col,target)
 assign('asap','ASAP_Hotspot',18)
 assign('fao','FAO_Category',17)
 # GRFC collector does not publish a reference period: leave it genuinely missing, never invent a date.
 if 'grfc' in src:
  for col in ['GRFC_Time_Period','GRFC_Period']:
   if col in src['grfc']:assign('grfc',col,14);break
 for col,target in [('CrisisWatch_Score',21),('ACLED_WCI_Normalized',22),('ACLED_Trends_Score',23)]:assign('conflict',col,target)
 if 'severity' in src:d[6]=pd.to_numeric(d[6],errors='coerce').fillna(0)
 d=compute(d)
 for c in [4,6]:
  vals=d[c].dropna()
  if not vals.between(0,10).all():errors.append(f'{headers[c]} contains invalid raw values outside 0-10; export blocked.')
  if d[c].isna().all():errors.append(f'{headers[c]} has no raw data.')
 if not set(d[23].dropna()).issubset({0,25,50,75,100}):errors.append('ACLED_Trends_Score is not categorical 0/25/50/75/100.')
 if 'conflict' in src:
  steps=pd.to_numeric(src['conflict']['CrisisWatch_Score'].reindex(d.index),errors='coerce').dropna()
  if not np.isclose(steps/(100/12),np.round(steps/(100/12)),atol=1e-6).all():errors.append('CrisisWatch score is not on the 100/12 increment grid.')
  stored=pd.to_numeric(src['conflict']['CERF_Conflict_Consolidated'].reindex(d.index),errors='coerce')
  diff=(stored-d[24]).abs()
  if diff.gt(1e-5).any():errors.append('Conflict processor result disagrees with its component formula.')
 if 'food' in src:
  recomputed=pd.Series([food_formula(*v) for v in d[[15,16,18,19]].itertuples(index=False,name=None)],index=d.index)
  diff=(recomputed-d[20]).abs()
  # Processor may have source-specific availability/override logic. Preserve it and surface differences.
  if diff.gt(1e-5).any():status=pd.concat([status,pd.DataFrame([{'source':'Food formula comparison','file':'processor authoritative','status':f'{int(diff.gt(1e-5).sum())} rows use processor availability/override rules','rows':len(d)}])],ignore_index=True)
 for c in [10,20,22,24,25,26,27,28]:
  if not d[c].dropna().between(0,100).all():errors.append(f'{headers[c]} outside 0-100; not silently clipped.')
 for c in [4,20,28]:
  if d[c].isna().any():errors.append(f'{headers[c]} missing for {int(d[c].isna().sum())} countries.')
 return wb,rows,headers,d,src,status,list(dict.fromkeys(errors))


def xml_cell(parent,coordinate,value,style=None,formula=None):
 attrs={'r':coordinate}
 if style is not None:attrs['s']=str(style)
 cell=ET.SubElement(parent,f'{{{NS}}}c',attrs)
 if formula:ET.SubElement(cell,f'{{{NS}}}f').text=formula.lstrip('=')
 if value is None or pd.isna(value):return cell
 if isinstance(value,(bool,np.bool_)):
  cell.set('t','b');ET.SubElement(cell,f'{{{NS}}}v').text='1' if value else '0'
 elif isinstance(value,(int,float,np.integer,np.floating)):
  ET.SubElement(cell,f'{{{NS}}}v').text=str(float(value))
 else:
  cell.set('t','inlineStr');is_=ET.SubElement(cell,f'{{{NS}}}is');ET.SubElement(is_,f'{{{NS}}}t').text=str(value)
 return cell


def source_xml(df):
 sheet=ET.Element(f'{{{NS}}}worksheet',nsmap={None:NS});sd=ET.SubElement(sheet,f'{{{NS}}}sheetData')
 for i,vals in enumerate([list(df.columns)]+list(df.itertuples(index=False,name=None)),1):
  row=ET.SubElement(sd,f'{{{NS}}}row',{'r':str(i)})
  for j,v in enumerate(vals,1):xml_cell(row,f'{get_column_letter(j)}{i}',v)
 return ET.tostring(sheet,encoding='utf-8',xml_declaration=True)



def _remove_grfc_period_from_export(payload):
    """Physically delete All Data column N, adjusting workbook references."""
    from openpyxl.formula.tokenizer import Tokenizer
    from openpyxl.utils.cell import column_index_from_string
    import copy

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    book = ET.fromstring(parts['xl/workbook.xml'])
    rels = ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
    sheets = list(book.find(f'{{{NS}}}sheets'))
    targets = {r.get('Id'): r.get('Target') for r in rels}

    def resolve(base, target):
        return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(base), target))

    paths = {s.get('name'): resolve('xl/workbook.xml', targets[s.get(f'{{{REL}}}id')]) for s in sheets}
    main_path = paths[SHEET]
    trees = {name: ET.fromstring(parts[path]) for name, path in paths.items()}
    removed = 14

    def endpoint(value):
        match = re.fullmatch(r'(\$?)([A-Z]{1,3})(\$?\d+)?', value)
        if not match:
            return None
        return match, column_index_from_string(match.group(2))

    def move_ref(value, allow_deleted=False):
        """A1 and column ranges; ranges shrink, single deleted refs fail closed."""
        ends = value.split(':')
        parsed = [endpoint(e) for e in ends]
        if not all(parsed) or len(ends) > 2:
            return value
        numbers = [p[1] for p in parsed]
        if len(numbers) == 1 and numbers[0] == removed:
            if allow_deleted:
                return None
            raise ValueError('A formula still references the deleted GRFC period cell: ' + value)
        if len(numbers) == 2 and numbers[0] == numbers[1] == removed:
            if allow_deleted:
                return None
            raise ValueError('A formula references only the deleted GRFC period column: ' + value)
        result = []
        for index, (match, number) in enumerate(parsed):
            if number > removed:
                number -= 1
            elif number == removed and len(numbers) == 2:
                number = removed if index == 0 else removed - 1
            result.append(match.group(1) + get_column_letter(number) + (match.group(3) or ''))
        return ':'.join(result)

    def formula(value, local_sheet=None):
        if not value:
            return value
        has_equal = value.startswith('=')
        tokenizer = Tokenizer(value if has_equal else '=' + value)
        for token in tokenizer.items:
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            text = token.value
            if '!' in text:
                qualifier, reference = text.rsplit('!', 1)
                sheet_name = qualifier.strip("'").replace("''", "'")
                if sheet_name != SHEET:
                    continue
                token.value = qualifier + '!' + move_ref(reference)
            elif local_sheet == SHEET:
                token.value = move_ref(text)
        output = ''.join(token.value for token in tokenizer.items)
        return ('=' if has_equal else '') + output

    # Formulas across all worksheets, including shared/array formula ranges.
    for name, tree in trees.items():
        for node in tree.iter():
            tag = ET.QName(node).localname
            if tag in ('f', 'formula', 'formula1', 'formula2') and node.text:
                node.text = formula(node.text, name)
        if name != SHEET:
            continue
        sd = tree.find(f'{{{NS}}}sheetData')
        for row in sd:
            row.attrib.pop('spans', None)
            for cell in list(row):
                coordinate = cell.get('r')
                if not coordinate:
                    continue
                updated = move_ref(coordinate, True)
                if updated is None:
                    row.remove(cell)
                else:
                    cell.set('r', updated)
        # All local cell/range metadata: merges, filters, validation, conditional
        # formatting, selections, dimensions, array/shared formula ranges, links.
        for node in list(tree.iter()):
            if ET.QName(node).localname == 'c':
                continue
            for attribute in ('ref', 'sqref', 'activeCell', 'topLeftCell'):
                if attribute not in node.attrib:
                    continue
                updated = [move_ref(v, True) for v in node.get(attribute).split()]
                updated = [v for v in updated if v]
                if updated:
                    node.set(attribute, ' '.join(updated))
                elif node.getparent() is not None:
                    node.getparent().remove(node)
            if ET.QName(node).localname == 'sqref' and node.text:
                node.text = ' '.join(v for v in (move_ref(x, True) for x in node.text.split()) if v)
        cols = tree.find(f'{{{NS}}}cols')
        if cols is not None:
            for col in list(cols):
                lo, hi = int(col.get('min')), int(col.get('max'))
                if lo == hi == removed:
                    cols.remove(col)
                    continue
                if lo > removed:
                    lo -= 1
                if hi >= removed:
                    hi -= 1
                col.set('min', str(lo)); col.set('max', str(hi))
        for parent in tree.iter():
            if ET.QName(parent).localname in ('mergeCells', 'dataValidations'):
                parent.set('count', str(len(parent)))

    # Defined names and print areas, respecting sheet-local names.
    for node in book.findall(f'.//{{{NS}}}definedName'):
        local = node.get('localSheetId')
        local_name = sheets[int(local)].get('name') if local is not None else None
        node.text = formula(node.text, local_name)

    # Table ranges and structured table columns belonging to All Data.
    rel_path = posixpath.join(posixpath.dirname(main_path), '_rels', posixpath.basename(main_path) + '.rels')
    related = ET.fromstring(parts[rel_path]) if rel_path in parts else []
    for relation in related:
        target = resolve(main_path, relation.get('Target'))
        kind = relation.get('Type', '').rsplit('/', 1)[-1]
        if target not in parts:
            continue
        if kind == 'table':
            table = ET.fromstring(parts[target]); old_range = table.get('ref')
            start = endpoint(old_range.split(':')[0])[1]
            columns = table.find(f'{{{NS}}}tableColumns')
            if columns is not None and start <= removed < start + len(columns):
                deleted_column = list(columns)[removed-start]
                label = deleted_column.get('name', '')
                # Do not silently leave broken structured references.
                if any('[' + label + ']' in (f.text or '') for t in trees.values() for f in t.findall(f'.//{{{NS}}}f')):
                    raise ValueError('A structured formula references the deleted period column.')
                columns.remove(deleted_column); columns.set('count', str(len(columns)))
            for node in table.iter():
                if node.get('ref'):
                    node.set('ref', move_ref(node.get('ref')))
                if ET.QName(node).localname.endswith('Formula') and node.text:
                    node.text = formula(node.text, SHEET)
            parts[target] = ET.tostring(table, encoding='utf-8', xml_declaration=True)
        elif kind == 'drawing':
            drawing = ET.fromstring(parts[target])
            for node in drawing.iter():
                if ET.QName(node).localname == 'col' and node.text and int(node.text) >= removed:
                    node.text = str(int(node.text)-1)
            parts[target] = ET.tostring(drawing, encoding='utf-8', xml_declaration=True)
        elif kind in ('comments', 'threadedComment'):
            comments = ET.fromstring(parts[target])
            for node in list(comments.iter()):
                if node.get('ref'):
                    updated = move_ref(node.get('ref'), True)
                    if updated:node.set('ref', updated)
                    elif node.getparent() is not None:node.getparent().remove(node)
            parts[target] = ET.tostring(comments, encoding='utf-8', xml_declaration=True)

    # Chart series formulas refer to All Data using sheet-qualified addresses.
    for name in list(parts):
        if name.startswith('xl/charts/') and name.endswith('.xml'):
            tree = ET.fromstring(parts[name])
            for node in tree.iter():
                if ET.QName(node).localname == 'f' and node.text:
                    node.text = formula(node.text)
            parts[name] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)

    for name, tree in trees.items():
        parts[paths[name]] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    # Drop the old calculation chain, which contains pre-deletion coordinates.
    parts.pop('xl/calcChain.xml', None)
    for node in list(rels):
        if node.get('Type', '').endswith('/calcChain'):
            rels.remove(node)
    types = ET.fromstring(parts['[Content_Types].xml'])
    for node in list(types):
        if node.get('PartName') == '/xl/calcChain.xml':types.remove(node)
    parts['xl/workbook.xml'] = ET.tostring(book, encoding='utf-8', xml_declaration=True)
    parts['xl/_rels/workbook.xml.rels'] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    parts['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():archive.writestr(name, content)
    return output.getvalue()

def export_xlsx(path,rows,data,sources,status):
 # Edit XML parts in place, preserving all original styles, drawings, conditional formatting and sheets.
 with zipfile.ZipFile(path) as z:parts={name:z.read(name) for name in z.namelist()}
 workbook=ET.fromstring(parts['xl/workbook.xml']);rels=ET.fromstring(parts['xl/_rels/workbook.xml.rels']);types=ET.fromstring(parts['[Content_Types].xml'])
 sheets=workbook.find(f'{{{NS}}}sheets')
 sheetnode=next(s for s in sheets if s.get('name')==SHEET)
 rid=sheetnode.get(f'{{{REL}}}id');target=next(r.get('Target') for r in rels if r.get('Id')==rid)
 sheetpath=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
 ws=ET.fromstring(parts[sheetpath]);sd=ws.find(f'{{{NS}}}sheetData');rowmap={int(r.get('r')):r for r in sd}
 for rownum,iso in zip(rows,data.index):
  row=rowmap[rownum];cells={c.get('r'):c for c in row}
  for col in VISIBLE:
   coord=f'{get_column_letter(col)}{rownum}';old=cells.get(coord);style=old.get('s') if old is not None else None
   # Preserve exact original formulas for calculated cells, with updated cached values.
   formula=None
   if col in [5,7,20,24,25,26,27,28] and old is not None:
    f=old.find(f'{{{NS}}}f');formula=f.text if f is not None else None
   if old is not None:row.remove(old)
   xml_cell(row,coord,data.loc[iso,col],style,formula)
  row[:]=sorted(row,key=lambda c:(len(re.match('[A-Z]+',c.get('r')).group()),re.match('[A-Z]+',c.get('r')).group()))
 # Keep original coordinates for formula fidelity, hide the two unwanted columns in the template export.
 cols=ws.find(f'{{{NS}}}cols')
 if cols is not None:
  for col in list(cols):
   lo,hi=int(col.get('min')),int(col.get('max'))
   if any(lo<=x<=hi for x in [3,9]):
    attrs=dict(col.attrib);cols.remove(col)
    for x in range(lo,hi+1):
     new=dict(attrs);new.update({'min':str(x),'max':str(x)})
     if x in [3,9]:new['hidden']='1'
     ET.SubElement(cols,f'{{{NS}}}col',new)
  cols[:]=sorted(cols,key=lambda c:int(c.get('min')))
 # Dynamic FAO export headings
 fao_headers=_dynamic_fao_titles(template_data(path)[2],sources)
 headerrow=rowmap.get(3)
 if headerrow is not None:
  for col in (16,17):
   coord=f'{get_column_letter(col)}3'
   old=next((c for c in headerrow if c.get('r')==coord),None)
   style=old.get('s') if old is not None else None
   if old is not None:headerrow.remove(old)
   xml_cell(headerrow,coord,fao_headers[col],style)
  headerrow[:]=sorted(headerrow,key=lambda c:(len(re.match('[A-Z]+',c.get('r')).group()),re.match('[A-Z]+',c.get('r')).group()))
 parts[sheetpath]=ET.tostring(ws,encoding='utf-8',xml_declaration=True)
 # Refresh dependent CIRV caches without changing their original formulas.
 cached=load_workbook(path,data_only=True)
 country_scores=dict(zip(data[1],data[28]))
 for dependent,colnum in [('CIRV Scores',2),('PowerBI',3)]:
  depnode=next((x for x in sheets if x.get('name')==dependent),None)
  if depnode is None:continue
  deprid=depnode.get(f'{{{REL}}}id');dep_target=next(r.get('Target') for r in rels if r.get('Id')==deprid)
  dep_path=dep_target.lstrip('/') if dep_target.startswith('/') else posixpath.normpath('xl/'+dep_target)
  dep=ET.fromstring(parts[dep_path]);depdata=dep.find(f'{{{NS}}}sheetData')
  for row in depdata:
   rownum=int(row.get('r'));country=cached[dependent].cell(rownum,1).value
   if country not in country_scores:continue
   coord=f'{get_column_letter(colnum)}{rownum}';old=next((c for c in row if c.get('r')==coord),None)
   formula=None;style=None
   if old is not None:
    style=old.get('s');f=old.find(f'{{{NS}}}f');formula=f.text if f is not None else None;row.remove(old)
   xml_cell(row,coord,country_scores[country],style,formula)
   row[:]=sorted(row,key=lambda c:(len(re.match('[A-Z]+',c.get('r')).group()),re.match('[A-Z]+',c.get('r')).group()))
  parts[dep_path]=ET.tostring(dep,encoding='utf-8',xml_declaration=True)
 # Original source sheets remain as August reference; current sheets are explicit and contain full audited schemas.
 datasets={f'Current {k}':v.reset_index(drop=True) for k,v in sources.items()}
 datasets['Source status']=status
 datasets['Export scope']=pd.DataFrame({'note':['Original source/reference sheets retained from August workbook.','Current source sheets contain local collector/processor outputs.','All Data and its cached calculations are current.','Historical funding/apportionment sheets are not refreshed; pre-existing funding #REF errors are retained.','GRFC time-period column removed from exported All Data.']})
 existing={s.get('name') for s in sheets};sid=max(int(s.get('sheetId')) for s in sheets)
 for name,df in datasets.items():
  name=name[:31]
  if name in existing:continue
  sid+=1;newrid=f'cirvCurrent{sid}';part=f'xl/worksheets/cirv_current_{sid}.xml'
  ET.SubElement(sheets,f'{{{NS}}}sheet',{'name':name,'sheetId':str(sid),f'{{{REL}}}id':newrid})
  ET.SubElement(rels,f'{{{PKG}}}Relationship',{'Id':newrid,'Type':REL+'/worksheet','Target':part[3:]})
  ET.SubElement(types,f'{{{CT}}}Override',{'PartName':'/'+part,'ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
  parts[part]=source_xml(df)
 parts['xl/workbook.xml']=ET.tostring(workbook,encoding='utf-8',xml_declaration=True)
 parts['xl/_rels/workbook.xml.rels']=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
 parts['[Content_Types].xml']=ET.tostring(types,encoding='utf-8',xml_declaration=True)
 out=BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,content in parts.items():z.writestr(name,content)
 return _remove_grfc_period_from_export(out.getvalue())


def colour(cell,wb):
 c=cell.fill.fgColor
 if cell.fill.patternType is None:return '#FFFFFF'
 if c.type=='rgb':return '#'+c.rgb[-6:]
 if c.type=='indexed':
  from openpyxl.styles.colors import COLOR_INDEX
  return '#'+COLOR_INDEX[c.indexed][-6:] if c.indexed<len(COLOR_INDEX) else '#FFFFFF'
 if c.type=='theme':
  root=ET.fromstring(wb.loaded_theme);scheme=root.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme')
  node=list(scheme)[c.theme][0];rgb=node.get('val') if node.tag.endswith('srgbClr') else node.get('lastClr','FFFFFF')
  a=[int(rgb[i:i+2],16) for i in (0,2,4)];t=c.tint
  return '#'+''.join(f'{round(v*(1+t) if t<0 else v+(255-v)*t):02X}' for v in a)
 return '#FFFFFF'



def table_html(wb, headers, data):
    """Display CIRV using the reference workbook's formatting."""
    from openpyxl.styles.colors import COLOR_INDEX
    from openpyxl.utils import get_column_letter
    from datetime import date, datetime as _datetime

    ws = wb[SHEET]
    visible = list(VISIBLE)

    def rgb(color, fallback=None):
        if color is None or color.type is None:
            return fallback

        if color.type == "rgb" and color.rgb:
            return "#" + str(color.rgb)[-6:]

        if color.type == "indexed" and color.indexed is not None:
            index = int(color.indexed)
            if index < len(COLOR_INDEX):
                return "#" + COLOR_INDEX[index][-6:]

        if color.type == "theme" and wb.loaded_theme:
            try:
                tree = ET.fromstring(wb.loaded_theme)
                scheme = tree.find(
                    ".//{http://schemas.openxmlformats.org/"
                    "drawingml/2006/main}clrScheme"
                )
                element = list(scheme)[int(color.theme)][0]
                base = element.get("val") or element.get("lastClr")

                if base:
                    tint = float(color.tint or 0)
                    values = [
                        int(base[i:i+2], 16)
                        for i in (0, 2, 4)
                    ]
                    values = [
                        round(
                            v * (1 + tint)
                            if tint < 0
                            else v + (255-v) * tint
                        )
                        for v in values
                    ]
                    return "#" + "".join(
                        f"{max(0, min(255, v)):02X}"
                        for v in values
                    )
            except (ValueError, IndexError, TypeError, AttributeError):
                pass

        return fallback

    def fill(cell):
        if cell.fill.patternType:
            return rgb(cell.fill.fgColor, "#FFFFFF")
        return "#FFFFFF"

    def css(cell, header=False):
        style = [f"background-color:{fill(cell)}"]
        color = rgb(cell.font.color, "#172536")

        style.extend([
            f"color:{color}",
            f"font-weight:{'700' if cell.font.bold else '400'}",
            f"font-style:{'italic' if cell.font.italic else 'normal'}",
            f"font-size:{max(9, min(17, float(cell.font.sz or 10)*1.25)):.1f}px"
        ])

        alignment = cell.alignment

        horizontal = {
            "center": "center",
            "right": "right",
            "left": "left"
        }.get(
            alignment.horizontal,
            "center" if header else "right"
        )

        vertical = {
            "top": "top",
            "bottom": "bottom",
            "center": "middle"
        }.get(alignment.vertical, "middle")

        style.append(f"text-align:{horizontal}")
        style.append(f"vertical-align:{vertical}")

        for side in ("top", "bottom", "left", "right"):
            border = getattr(cell.border, side)

            if border and border.style:
                width = (
                    "2px"
                    if border.style in ("medium", "thick", "double")
                    else "1px"
                )
                border_color = rgb(border.color, "#9BA9B5")
                style.append(
                    f"border-{side}:{width} solid {border_color}"
                )

        if not any(x.startswith("border-") for x in style):
            style.append("border:1px solid #D7DEE5")

        return ";".join(style)

    def width(col):
        dimension = ws.column_dimensions.get(
            get_column_letter(col)
        )

        excel_width = (
            dimension.width
            if dimension and dimension.width
            else ws.sheet_format.defaultColWidth or 8.43
        )

        return max(58, min(300, round(excel_width * 7.2 + 10)))

    widths = {col: width(col) for col in visible}

    first_height = max(
        38, round((ws.row_dimensions[1].height or 30) * 1.2)
    )
    second_height = max(
        38, round((ws.row_dimensions[2].height or 30) * 1.2)
    )
    header_height = max(
        75,
        min(170, round((ws.row_dimensions[3].height or 45) * 2))
    )

    parts = [
        '<div style="overflow:auto;max-height:72vh;width:100%;'
        'border:1px solid #B9C9D6">',
        '<table style="border-collapse:separate;border-spacing:0;'
        'table-layout:fixed;font-family:Arial,sans-serif;font-size:12px">',
        '<colgroup>'
    ]

    for col in visible:
        parts.append(
            f'<col style="width:{widths[col]}px;'
            f'min-width:{widths[col]}px">'
        )

    parts.append("</colgroup><thead>")

    def grouped_row(rownum, height, top):
        groups = []

        for col in visible:
            merged = next(
                (
                    r for r in ws.merged_cells.ranges
                    if r.min_row <= rownum <= r.max_row
                    and r.min_col <= col <= r.max_col
                ),
                None
            )

            anchor = merged.min_col if merged else col

            if groups and groups[-1][0] == anchor:
                groups[-1][1].append(col)
            else:
                groups.append((anchor, [col]))

        parts.append("<tr>")

        for anchor, cols in groups:
            cell = ws.cell(rownum, anchor)
            label = html.escape(str(cell.value or ""))

            sticky = (
                "left:0;z-index:9;"
                if 1 in cols
                else ""
            )

            parts.append(
                f'<th colspan="{len(cols)}" '
                f'style="{css(cell, True)};'
                f'height:{height}px;padding:4px 6px;'
                f'white-space:normal;overflow-wrap:anywhere;'
                f'position:sticky;top:{top}px;z-index:7;'
                f'{sticky}">{label}</th>'
            )

        parts.append("</tr>")

    grouped_row(1, first_height, 0)
    grouped_row(2, second_height, first_height)

    parts.append("<tr>")

    for col in visible:
        cell = ws.cell(3, col)
        label = html.escape(str(headers.get(col, "")).strip())

        sticky = (
            "left:0;z-index:10;"
            if col == 1
            else ""
        )

        parts.append(
            f'<th style="{css(cell, True)};'
            f'height:{header_height}px;padding:5px;'
            f'white-space:normal;overflow-wrap:anywhere;'
            f'line-height:1.15;position:sticky;'
            f'top:{first_height + second_height}px;'
            f'z-index:8;{sticky}">{label}</th>'
        )

    parts.append("</tr></thead><tbody>")

    def value_text(value, cell):
        if value is None or pd.isna(value):
            return ""

        if isinstance(value, (date, _datetime)):
            return value.strftime("%d/%m/%Y")

        if isinstance(
            value, (float, int, np.integer, np.floating)
        ) and not isinstance(value, bool):

            fmt = cell.number_format or "General"

            if "%" in fmt:
                match = re.search(r"0\.(0+)", fmt)
                decimals = len(match.group(1)) if match else 0
                return f"{float(value)*100:,.{decimals}f}%"

            match = re.search(r"0\.(0+)", fmt)

            if match:
                return f"{float(value):,.{len(match.group(1))}f}"

            if "0" in fmt and fmt != "General":
                return f"{float(value):,.0f}"

            if isinstance(value, (float, np.floating)):
                return f"{float(value):.2f}"

            return str(value)

        return str(value)

    # Pre-index workbook rows to preserve styles when filtering.
    reference_rows = {
        str(ws.cell(r, 2).value): r
        for r in range(5, ws.max_row + 1)
        if ws.cell(r, 2).value is not None
    }

    for iso, row in data.iterrows():
        refrow = reference_rows.get(str(iso), 5)

        parts.append("<tr>")

        for col in visible:
            cell = ws.cell(refrow, col)
            value = html.escape(value_text(row[col], cell))

            sticky = (
                "position:sticky;left:0;z-index:3;"
                if col == 1
                else ""
            )

            parts.append(
                f'<td style="{css(cell)};height:25px;'
                f'padding:3px 6px;white-space:normal;'
                f'overflow-wrap:anywhere;{sticky}">'
                f'{value}</td>'
            )

        parts.append("</tr>")

    parts.append("</tbody></table></div>")

    return "".join(parts)



def render_fts_scatterplots(cirv_data):
 import streamlit as st
 import pandas as pd
 import numpy as np
 import plotly.graph_objects as go

 root = Path(__file__).resolve().parent
 funding_path = root / "data" / "processed" / "fts_country_combined.csv"
 annual_path = root / "data" / "processed" / "fts_country_annual.csv"

 st.markdown("## CIRV vs Humanitarian Funding")

 if not funding_path.exists() or not annual_path.exists():
  st.info("FTS funding datasets are unavailable.")
  return

 funding = pd.read_csv(funding_path)
 annual = pd.read_csv(annual_path)

 # Default to HNRP plans only.
 show_all = st.toggle(
  "Include all coordinated plans",
  value=False,
  help="Off: HNRP countries only. On: all eligible coordinated plans."
 )

 if not show_all:
  hnrp = annual[
   annual["plan_type"]
   .fillna("")
   .str.lower()
   .str.contains("humanitarian needs and response plan|humanitarian response plan")
  ]

  eligible_iso = set(hnrp["iso3"])
  funding = funding[funding["iso3"].isin(eligible_iso)]

 cirv = pd.DataFrame({
  "iso3": cirv_data[2].astype(str).str.strip().str.upper(),
  "cirv_score": pd.to_numeric(cirv_data[28], errors="coerce")
 })

 # Match country names directly from the CIRV table.
 cirv_names = pd.DataFrame({
  "iso3": cirv_data[2].astype(str).str.strip().str.upper(),
  "cirv_country": cirv_data[1].astype(str).str.strip()
 })

 cirv_names = cirv_names.drop_duplicates("iso3")

 merged = funding.merge(cirv, on="iso3", how="left")
 merged = merged.merge(cirv_names, on="iso3", how="left")

 # Use CIRV names for chart labels and tooltips.
 merged["country"] = merged["cirv_country"].fillna(
  merged["country"]
 )

 merged = merged.drop(columns=["cirv_country"])

 charts = [
  (
   "2025 + 2026 Coordinated Plans",
   "coverage_2025_2026",
   "requirements_combined",
   "funded_combined"
  ),
  (
   "2026 Coordinated Plans",
   "coverage_2026_plan",
   "requirements_usd_2026",
   "funded_usd_2026"
  ),
  (
   "2026 Total Funding",
   "coverage_2026_total",
   "requirements_usd_2026",
   "total_funded_usd_2026"
  )
 ]

 for title, coverage_col, req_col, funded_col in charts:

  st.markdown("### " + title)

  plot = merged[
   ["country", "iso3", "cirv_score", coverage_col, req_col, funded_col]
  ].copy()

  plot = plot.dropna()
  plot = plot[plot[req_col] > 0]

  if plot.empty:
   st.warning("No eligible countries for this comparison.")
   continue

  plot["coverage_pct"] = plot[coverage_col] * 100

  # Bubble areas proportional to requirements.
  maximum = plot[req_col].max()
  sizeref = 2 * maximum / (75 ** 2)

  # Detect extreme funding coverage values.
  q1 = plot["coverage_pct"].quantile(0.25)
  q3 = plot["coverage_pct"].quantile(0.75)
  iqr = q3 - q1

  upper_limit = max(100.0, q3 + 1.5 * iqr)

  outliers = plot[
   plot["coverage_pct"] > upper_limit
  ].copy()

  regular = plot[
   plot["coverage_pct"] <= upper_limit
  ].copy()

  show_full_axis = st.toggle(
   "Show full X-axis including extreme values",
   value=False,
   key="full_axis_" + coverage_col
  )

  fig = go.Figure()

  fig.add_trace(go.Scatter(
   x=plot["coverage_pct"],
   y=plot["cirv_score"],
   mode="markers+text",
   text=plot["country"],
   textposition="top center",
   textfont=dict(size=15, color="#263238"),
   marker=dict(
    size=plot[req_col],
    sizemode="area",
    sizeref=sizeref,
    sizemin=10,
    color="#4F81BD",
    opacity=0.48,
    line=dict(width=1.5, color="#245580")
   ),
   customdata=plot[[req_col, funded_col]].to_numpy(),
   hovertemplate=(
    "<b>%{text}</b><br>"
    "Funding coverage: %{x:.1f}%<br>"
    "CIRV: %{y:.1f}<br>"
    "Requirements: $%{customdata[0]:,.0f}<br>"
    "Funding: $%{customdata[1]:,.0f}"
    "<extra></extra>"
   ),
   showlegend=False
  ))

  mean_x = plot["coverage_pct"].mean()
  mean_y = plot["cirv_score"].mean()

  fig.add_vline(
   x=mean_x,
   line_dash="dash",
   line_color="#777777",
   line_width=2
  )

  fig.add_hline(
   y=mean_y,
   line_dash="dash",
   line_color="#777777",
   line_width=2
  )

  # Keep all observations and averages unchanged.
  # Only adjust the visible X-axis range.
  if not show_full_axis and not regular.empty:
   axis_max = max(
    100.0,
    regular["coverage_pct"].max() * 1.12
   )

   fig.update_xaxes(range=[0, axis_max])

  fig.update_layout(
   height=850,
   margin=dict(l=95, r=100, t=60, b=100),
   paper_bgcolor="white",
   plot_bgcolor="white",
   font=dict(size=17, color="#263238"),
   xaxis=dict(
    title=dict(
     text="Funding coverage against requirements (%)",
     font=dict(size=21)
    ),
    tickfont=dict(size=17),
    ticksuffix="%",
    showgrid=True,
    gridcolor="#E5E5E5",
    zeroline=False
   ),
   yaxis=dict(
    title=dict(
     text="CIRV Score",
     font=dict(size=21)
    ),
    tickfont=dict(size=17),
    showgrid=True,
    gridcolor="#E5E5E5",
    zeroline=False
   ),
   hoverlabel=dict(font_size=16)
  )

  st.plotly_chart(
   fig,
   use_container_width=True,
   key="fts_" + coverage_col
  )

  st.markdown(
   f"**Average funding coverage:** {mean_x:.1f}%"
   f" &nbsp;&nbsp; | &nbsp;&nbsp; "
   f"**Average CIRV:** {mean_y:.1f}"
   f" &nbsp;&nbsp; | &nbsp;&nbsp; "
   f"**Countries:** {len(plot)}",
   unsafe_allow_html=True
  )

  st.markdown(
   "<div style='font-size:16px;line-height:1.6;color:#555;'>Countries without comparable funding data or a valid CIRV "
   "score are excluded. Multi-country regional and global plans "
   "are excluded because they cannot be assigned a single-country "
   "CIRV score. Bubble size represents coordinated-plan requirements."
   "</div>",
   unsafe_allow_html=True
  )

  if not outliers.empty:

   st.markdown("**Extreme funding coverage values:**")

   for _, row in outliers.sort_values(
    "coverage_pct",
    ascending=False
   ).iterrows():

    st.markdown(
     f"* **{row['country']}**: "
     f"{row['coverage_pct']:.1f}% funding coverage; "
     f"CIRV {row['cirv_score']:.1f}. "
     "Outside the default X-axis range."
    )

  st.download_button(
   "Download chart data",
   plot.to_csv(index=False).encode("utf-8-sig"),
   file_name="CIRV_" + coverage_col + ".csv",
   mime="text/csv",
   key="download_" + coverage_col
  )


def main():
 import streamlit as st
 st.set_page_config(page_title='CERF CIRV',layout='wide',page_icon=get_page_icon());st.title('CERF CIRV | All Data')
 try:path=reference();wb,rows,headers,data,sources,status,errors=assemble(path,root=refresh_controls())
 except Exception as exc:st.error(str(exc));st.stop()
 with st.expander('Every collector and processor output',expanded=bool(errors)):st.dataframe(status,hide_index=True,use_container_width=True)
 for error in errors:st.error(error)
 st.caption('Live local outputs only. No historical workbook data substituted for missing current sources.')
 q=st.text_input('Filter country / ISO3')
 view=data[data[1].astype(str).str.contains(q,case=False,regex=False)|data[2].str.contains(q,case=False,regex=False)] if q else data
 st.markdown(table_html(wb,headers,view),unsafe_allow_html=True)
 render_fts_scatterplots(view)
 for key,df in sources.items():
  with st.expander('Source sheet: '+key):st.dataframe(df.reset_index(drop=True),hide_index=True,use_container_width=True)
 if errors:st.warning('Complete export blocked until required source errors are resolved. Source sheets remain available for inspection.')
 else:
  flat=data[VISIBLE].rename(columns=headers)
  st.download_button('Download All Data CSV',flat.to_csv(index=False).encode('utf-8-sig'),'CERF_CIRV_All_Data_Current.csv','text/csv')
  st.download_button('Download workbook + every current source sheet',export_xlsx(path,rows,data,sources,status),'CERF_CIRV_Current.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__=='__main__':main()
