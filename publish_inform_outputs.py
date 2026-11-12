"""Publish the existing INFORM collector DataFrames. No credential handling."""
from pathlib import Path
import argparse
import pandas as pd
ROOT=Path(__file__).resolve().parent

def publish(refresh=False):
 from collectors import inform_risk,inform_severity
 for key,module in [('risk',inform_risk),('severity',inform_severity)]:
  if refresh:
   release=getattr(module,'discover_latest_inform_'+key)()
   path=getattr(module,'download_inform_'+key)(release)
  else:
   paths=list((ROOT/'data'/'raw'/('inform_'+key)).rglob('*.xlsx'))
   if not paths:raise FileNotFoundError(f'No downloaded INFORM {key} workbook. Run with --refresh to use your existing collector.')
   path=max(paths,key=lambda p:p.stat().st_mtime)
  data=getattr(module,'extract_inform_'+key)(path)
  raw='INFORM_'+key.capitalize()+'_Raw'
  if raw not in data:raise ValueError(f'Existing collector did not return {raw}.')
  data[raw]=pd.to_numeric(data[raw],errors='raise')
  if not data[raw].between(0,10).all():raise ValueError('INFORM raw scale is not 0-10.')
  if data.ISO3.duplicated().any():raise ValueError('Duplicate INFORM ISO3 records.')
  data['Source_File']=path.name
  out=ROOT/f'inform_{key}_current.csv';data.to_csv(out,index=False,encoding='utf-8-sig')
  print(f'Published {out.name}: {len(data)} rows; raw range {data[raw].min()} to {data[raw].max()}')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');args=parser.parse_args();publish(args.refresh)
