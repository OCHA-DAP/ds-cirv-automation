from pathlib import Path
import os, sys, json, shutil, subprocess, uuid, time, argparse, importlib.util
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.cirv_refresh'

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(tmp,path)

def status():
 try:return json.loads((RUNTIME/'status.json').read_text())
 except (OSError,ValueError):return {'state':'idle'}

def start(mode='all',outlook=False):
 RUNTIME.mkdir(exist_ok=True)
 lock=RUNTIME/'lock'
 try:lock.mkdir()
 except FileExistsError:return False,'A refresh is already running, or a previous lock needs inspection.'
 try:
  atomic(RUNTIME/'status.json',{'state':'starting','mode':mode,'started':time.time()})
  cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--mode',mode]
  if outlook:cmd.append('--outlook')
  p=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  atomic(lock/'owner.json',{'pid':p.pid})
  return True,'Background refresh started.'
 except Exception:
  shutil.rmtree(lock,ignore_errors=True);raise

def active_root():
 try:
  p=Path(json.loads((RUNTIME/'active.json').read_text())['path'])
  return p if p.is_dir() else ROOT
 except (OSError,ValueError,KeyError):return ROOT

def worker(mode,outlook):
 run=uuid.uuid4().hex;stage=RUNTIME/'work'/run;log=RUNTIME/'logs'/f'{run}.log';log.parent.mkdir(parents=True,exist_ok=True)
 state={'state':'running','mode':mode,'started':time.time(),'log':str(log)}
 def report(**kw):state.update(kw);atomic(RUNTIME/'status.json',state)
 try:
  # Isolate writes: collectors/processors never overwrite the live project's CSVs.
  ignore=shutil.ignore_patterns('.cirv_refresh','.venv','venv','env','.git','__pycache__','backups','node_modules','*.zip','*.bak')
  shutil.copytree(ROOT,stage,ignore=ignore)
  # Recalculation starts from the latest published CSVs, not stale originals.
  active=active_root()
  if active!=ROOT:
   for p in active.rglob('*.csv'):
    target=stage/p.relative_to(active);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  commands=[]
  if mode=='all':
   commands.append(('INFORM Risk and Severity',[sys.executable,'publish_inform_outputs.py','--refresh']))
   modules=['hdx_ipc','fewsnet_faob','grfc','fao_crop_prospects','asap_hotspots','sofi','acled_wci','acled_trends','crisiswatch']
   if outlook:modules.append('iasc_outlook')
   modules+=['iasc_horizon','iasc_scaleup']
   commands += [(m,[sys.executable,'-m','collectors.'+m]) for m in modules]
  commands += [(m,[sys.executable,'-m','processors.'+m]) for m in ['food_security','conflict','iasc']]
  with log.open('w',encoding='utf-8') as output:
   for index,(name,cmd) in enumerate(commands,1):
    report(step=name,completed=index-1,total=len(commands))
    output.write('\nSTEP '+name+'\n');output.flush()
    result=subprocess.run(cmd,cwd=stage,stdout=output,stderr=subprocess.STDOUT,timeout=3600,env={**os.environ,'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8'})
    if result.returncode:raise RuntimeError(f'{name} failed (exit {result.returncode}). See refresh log.')
  report(step='Validate completed outputs')
  spec=importlib.util.spec_from_file_location('cirv_validation',stage/'cirv_all_data_app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
  result=app.assemble(app.reference(stage),root=stage)
  errors=result[-1]
  if errors:raise RuntimeError('App validation failed: '+'; '.join(map(str,errors)))
  snapshot=RUNTIME/'snapshots'/run;snapshot.mkdir(parents=True)
  for p in stage.rglob('*.csv'):
   target=snapshot/p.relative_to(stage);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  # One pointer switch publishes the entire validated snapshot.
  atomic(RUNTIME/'active.json',{'path':str(snapshot),'completed':time.time(),'run':run})
  report(state='succeeded',step='Published validated outputs',finished=time.time(),completed=len(commands))
 except Exception as exc:report(state='failed',error=str(exc),finished=time.time())
 finally:
  shutil.rmtree(stage,ignore_errors=True);shutil.rmtree(RUNTIME/'lock',ignore_errors=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');parser.add_argument('--mode',choices=['all','processors'],default='all');parser.add_argument('--outlook',action='store_true');args=parser.parse_args()
 if args.worker:worker(args.mode,args.outlook)
 else:print(start(args.mode,args.outlook)[1])
