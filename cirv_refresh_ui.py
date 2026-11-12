from pathlib import Path
import json, os
import cirv_refresh_runner as runner

def refresh_controls():
 import streamlit as st
 settings=runner.RUNTIME/'settings.json'
 try:config=json.loads(settings.read_text())
 except (OSError,ValueError):config={'startup':False}
 @st.cache_resource
 def server_start_once():
  if config.get('startup'):runner.start('all',False)
  return True
 server_start_once()
 with st.expander('Data refresh controls',expanded=True):
  auto=st.checkbox('Refresh all sources once when this app server starts',value=config.get('startup',False))
  if auto!=config.get('startup',False):
   runner.atomic(settings,{'startup':auto})
   st.caption('Saved. Takes effect on the next server restart, not on every page rerun.')
  outlook=st.checkbox('Include Outlook collection (may require interactive sign-in)',value=False)
  state=runner.status();busy=state.get('state') in ['starting','running']
  a,b,c=st.columns(3)
  if a.button('Refresh all source data',disabled=busy):
   ok,message=runner.start('all',outlook);st.info(message);st.rerun()
  if b.button('Recalculate processors only',disabled=busy):
   ok,message=runner.start('processors');st.info(message);st.rerun()
  if c.button('Reload results / status'):st.rerun()
  st.write('Refresh status:',state.get('state','idle'))
  if state.get('step'):st.write('Current / last step:',state['step'])
  if state.get('error'):st.error(state['error'])
  if state.get('log'):
   p=Path(state['log'])
   if p.exists():st.code(p.read_text(encoding='utf-8',errors='replace')[-12000:],language='text')
  st.caption('The table reads the last successful snapshot. Failed jobs do not publish partial results. Reload after success.')
 return runner.active_root()
