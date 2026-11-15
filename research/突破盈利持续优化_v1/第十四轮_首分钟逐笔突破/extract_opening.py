"""Resolve opening-minute triggers with checksum-verified public trade tapes."""
import concurrent.futures,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
sys.path.insert(0,str(HERE.parent/'第六轮_柱内首次触价'))
from extract_touch_trades import task
M=60_000
def main():
    d=pd.concat([pd.read_parquet(HERE/f'首分钟潜在候选_{y}.parquet') for y in (2024,2026)],ignore_index=True)
    tasks=[(c,day,g.to_dict('records')) for (c,day),g in d.groupby(['contract','day'])]
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(task,t) for t in tasks]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results)%20==0:print('OPENING_ARCHIVES',len(results),'/',len(tasks),flush=True)
    rows=[r for result in results for r in result.pop('rows')];out=pd.DataFrame(rows)
    assert len(out)==len(d);mismatches=[]
    for (year,contract),g in out[out.status.eq('verified')].groupby(['source_year','contract']):
        norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        for idx,r in g.iterrows():
            b=raw.loc[int(r.ts)];ending=raw.loc[int(r.quarter_end)-M]
            good=(np.isfinite([b.high,b.low,b.close,ending.close]).all() and r.suffix_high<=b.high*(1+1e-9)
                  and r.suffix_low>=b.low*(1-1e-9) and np.isclose(r.suffix_close,b.close,rtol=1e-9,atol=1e-12)
                  and r.entry_exec_ts>=r.decision_ts+5000 and r.entry_exec_ts<r.quarter_end)
            if not good:mismatches.append(r.observation_id)
            opening=float(raw.at[int(r.quarter_start),'open']);closing=float(ending.close)
            body=int(r.side)*(closing-opening)/opening;beyond=int(r.side)*(closing-float(r.level))>0
            out.loc[idx,'large_1pct_label']=bool(body>=.01 and beyond)
            out.loc[idx,'large_halfpct_label']=bool(body>=.005 and beyond)
            out.loc[idx,'completed_body_pct']=100*body
    out.loc[out.observation_id.isin(mismatches),'status']='minute_archive_mismatch'
    out.to_parquet(HERE/'首分钟首次触价与五秒参考.parquet',index=False)
    meta={'possible_events':len(d),'daily_archives':len(tasks),'verified_archives':sum(r['status']=='verified' for r in results),
          'statuses':out.status.value_counts().to_dict(),'minute_mismatch':mismatches,
          'archive_errors':[r for r in results if r['status']!='verified'],
          'bytes_downloaded':sum(r.get('bytes',0) for r in results),'archives':results,
          'note':'Aggregated public trades and their official checksums; no exchange order or guaranteed fill.'}
    (HERE/'首分钟逐笔校验档案.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OPENING_EXTRACTION_COMPLETE',json.dumps({k:meta[k] for k in ['possible_events','daily_archives','statuses','minute_mismatch','archive_errors','bytes_downloaded']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
