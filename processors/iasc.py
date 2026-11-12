from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HORIZON = ROOT / 'iasc_horizon_current.csv'
SCALEUP_CANDIDATES = [
    ROOT / 'iasc_scaleup_current.csv',
    ROOT / 'data' / 'processed' / 'iasc_scaleup_current.csv',
]
OUT = ROOT / 'iasc_current.csv'
PROCESSED_OUT = ROOT / 'data' / 'processed' / 'iasc_current.csv'

SERIOUSNESS_TO_SCORE = {
    'very low': 0.0,
    'low': 0.0,
    'moderate': 33.0,
    'high': 67.0,
    'very high': 100.0,
}
SCORE_TO_SERIOUSNESS = {0.0:'Low',33.0:'Moderate',67.0:'High',100.0:'Very High'}

def _first(df, names, required=False):
    for name in names:
        if name in df.columns:
            return name
    if required:
        raise RuntimeError('Missing required column; expected one of: '+', '.join(names))
    return None

def _truthy(v):
    if pd.isna(v): return False
    return str(v).strip().lower() in {'1','true','yes','y','active'}

def _score(v):
    if pd.isna(v): return 0.0
    n=pd.to_numeric(pd.Series([v]), errors='coerce').iloc[0]
    if pd.notna(n): return float(n)
    key=str(v).strip().lower()
    if key not in SERIOUSNESS_TO_SCORE:
        raise RuntimeError(f'Unknown IASC seriousness value: {v!r}')
    return SERIOUSNESS_TO_SCORE[key]

def process_iasc():
    if not HORIZON.exists():
        raise FileNotFoundError(f'Missing Horizon collector output: {HORIZON}')
    h=pd.read_csv(HORIZON,encoding='utf-8-sig',low_memory=False)
    iso=_first(h,['ISO3','ISO3 Country Code'],True)
    country=_first(h,['CERF_Country','Country','country'],True)
    score_col=_first(h,['IASC_Early_Warning_Score','IASC Horizon Score','IASC_Horizon_Score'],True)
    serious_col=_first(h,['IASC_Early_Warning_Seriousness','IASC Early Warning - Seriousness'])
    type_col=_first(h,['IASC_Early_Warning_Type','IASC Early Warning - Type'])
    hscore=h[score_col].apply(_score).clip(0,100)

    active=pd.Series(False,index=h.index); scale_score=pd.Series(0.0,index=h.index)
    scale_path=next((p for p in SCALEUP_CANDIDATES if p.exists()),None)
    if scale_path:
        s=pd.read_csv(scale_path,encoding='utf-8-sig',low_memory=False)
        siso=_first(s,['ISO3','ISO3 Country Code'],True)
        active_col=_first(s,['IASC_ScaleUp_Active','ScaleUp_Active','Active','active','Status'])
        score2_col=_first(s,['IASC_ScaleUp_Score','ScaleUp_Score','Score'])
        smap={}
        for _,r in s.iterrows():
            a=_truthy(r[active_col]) if active_col else (_score(r[score2_col])>=100 if score2_col else False)
            sc=_score(r[score2_col]) if score2_col else (100.0 if a else 0.0)
            smap[str(r[siso]).strip().upper()] = (a,sc)
        vals=h[iso].astype(str).str.upper().map(smap)
        active=vals.apply(lambda v: bool(v[0]) if isinstance(v,tuple) else False)
        scale_score=vals.apply(lambda v: float(v[1]) if isinstance(v,tuple) else 0.0)

    # Workbook parity: IASC contributes directly on the 0-100 scale. The workbook's
    # E. CERF Multi-Indicator formula then weights J (IASC) 5/33.
    final=pd.concat([hscore,scale_score.where(active,0.0)],axis=1).max(axis=1).clip(0,100)
    out=pd.DataFrame({
        'CERF_Country':h[country], 'ISO3':h[iso],
        'IASC_Early_Warning_Seriousness':h[serious_col] if serious_col else final.map(SCORE_TO_SERIOUSNESS),
        'IASC_Early_Warning_Type':h[type_col] if type_col else pd.NA,
        'IASC_Horizon_Score':hscore,
        'IASC_ScaleUp_Active':active,
        'IASC_ScaleUp_Score':scale_score.where(active,0.0),
        'CERF_IASC_Consolidated':final,
        'IASC_Early_Warning_Score':final,
    })
    if out['ISO3'].duplicated().any(): raise RuntimeError('Duplicate ISO3 values in IASC output.')
    OUT.parent.mkdir(parents=True,exist_ok=True); PROCESSED_OUT.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(OUT,index=False,encoding='utf-8-sig'); out.to_csv(PROCESSED_OUT,index=False,encoding='utf-8-sig')
    print('IASC PROCESSOR COMPLETE')
    print('Countries:',len(out)); print('Active Scale-Up overrides:',int(active.sum()))
    print(out[out.CERF_IASC_Consolidated>0][['CERF_Country','ISO3','IASC_Horizon_Score','IASC_ScaleUp_Active','CERF_IASC_Consolidated']].to_string(index=False))
    return out

if __name__=='__main__': process_iasc()
