"""Regenerate causal first-touch candidates using the original 18-symbol ranking."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
opening=load('expanded18_opening',PARENT/'第十四轮_首分钟逐笔突破'/'generate_opening.py')
later=load('expanded18_later',PARENT/'第六轮_柱内首次触价'/'generate_touch_candidates.py')
opening.HERE=HERE;later.HERE=HERE;f=flow.forward;M=60_000
original=json.loads((PARENT.parent/'突破胜率与净收益前瞻检验_v1'/'冻结研究方案.json').read_text(encoding='utf-8'))
assert len(original['fixed_pool'])==18
f.plan['fixed_pool']=original['fixed_pool']
def configure(year):
    if year==2024:
        f.NORM=ROOT/'work'/'breakout_2024_expanded18'/'normalized';warm='2023-12-01';start='2024-01-01';end='2024-07-01'
    elif year==2026:
        f.NORM=ROOT/'work'/'breakout_november_2026'/'normalized';warm='2026-04-01';start='2026-05-01';end='2026-08-01'
    else:raise ValueError(year)
    f.WARM=int(pd.Timestamp(warm,tz='UTC').timestamp()*1000);f.START=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    f.END=int(pd.Timestamp(end,tz='UTC').timestamp()*1000);f.GRID=np.arange(f.WARM,f.END,M,dtype=np.int64)
r2.configure=configure
def main():
    meta=json.loads((HERE/'新增七币2024档案校验.json').read_text(encoding='utf-8'))
    if meta['errors']:raise RuntimeError('new_month_archive_errors')
    # Both functions use only prior features to determine which directions could be admitted.
    opening.generate(2024,'2024-01-01','2024-06-30');opening.generate(2026,'2026-05-01','2026-07-31')
    later.generate(2024,'2024-01-01','2024-06-30','expanded_2024')
    later.generate(2026,'2026-05-01','2026-07-31','expanded_2026')
    pieces=[]
    for year in (2024,2026):
        first=pd.read_parquet(HERE/f'首分钟潜在候选_{year}.parquet');first['cohort']='opening'
        rest=pd.read_parquet(HERE/f'潜在触价候选_expanded_{year}.parquet');rest['cohort']='later';rest['source_year']=str(year)
        rest['day']=pd.to_datetime(rest.trigger_minute,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        pieces.extend([first,rest])
    d=pd.concat(pieces,ignore_index=True).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert d.observation_id.is_unique and not d.duplicated(['symbol','quarter_start']).any()
    d.to_parquet(HERE/'十八币潜在首次触价.parquet',index=False)
    out={'possible_events':len(d),'by_year':d.source_year.value_counts().to_dict(),
         'by_cohort':d.cohort.value_counts().to_dict(),'by_symbol':d.symbol.value_counts().to_dict(),
         'note':'Potential minutes only; same-minute first direction and 5s reference must be tape verified.'}
    flow.dump(HERE/'十八币潜在触价统计.json',out);print('EXPANDED18_CANDIDATES',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
