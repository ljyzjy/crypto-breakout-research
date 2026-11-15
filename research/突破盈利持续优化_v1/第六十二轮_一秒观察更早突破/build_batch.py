"""Build a candidate-complete batch; source unknowns and pending groups persist."""
import json,sys
from pathlib import Path
import pandas as pd
import run_observation as runner
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent
KNOWN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def main(year):
    candidates,baseline,paths,proof=runner.inputs(year);I=H/f'{year}冻结输入';OUT=H/f'{year}一秒观察分批';OUT.mkdir(exist_ok=True)
    d=candidates[candidates.observation_id.isin(proof)];fp=runner.fingerprint(year);work=ROOT/'work'/f'oneobs62_{year}'/'tape'
    rows={};archives=[]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));cp=work/(runner.key(fp,spec)+'.json')
        if not cp.exists():
            for obs in g.observation_id:rows[obs]={'status':'archive_pending'}
            continue
        z=json.loads(cp.read_text(encoding='utf-8'));assert z['status']=='verified';archives.append({k:v for k,v in z.items() if k!='rows'})
        for r in z['rows']:assert r['observation_id'] not in rows;rows[r['observation_id']]=r
    for obs in set(candidates.observation_id)-set(proof):rows[obs]={'status':'prior_source_unknown'}
    assert set(rows)==set(candidates.observation_id)
    signals=[];newpaths=[]
    for e in candidates.to_dict('records'):
        obs=e['observation_id'];r=rows[obs];pre=r.get('prechecks',{})
        for variant,v in r.get('paths',{}).items():newpaths.append({'observation_id':obs,'variant':variant,**v})
        signal={k:v for k,v in r.items() if k not in ('paths','prechecks')}
        signal.update({'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
        signals.append({**e,**signal})
    sig=pd.DataFrame(signals);p=pd.DataFrame(newpaths)
    if not len(p):p=pd.DataFrame(columns=['observation_id','variant','status'])
    assert not p.duplicated(['observation_id','variant']).any();sig.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False)
    p.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    unknown=sig.loc[~sig.status.isin(KNOWN),'observation_id'].tolist()
    quality={'candidate_events':len(sig),'event_statuses':sig.status.value_counts().to_dict(),
        'unexpected_event_count':len(unknown),'variant_paths':len(p),'unverified_path_count':int((~p.status.eq('verified')).sum()),
        'archive_errors':[{'status':'unresolved','events':unknown}] if unknown else [],'archives':archives,
        'note':'Prior source unknown, new inconsistencies and pending archives are explicit; only first breakout, no retry.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    execution={'research_plan_sha256':runner.sha(H/'冻结研究方案.md'),'original_execution_sha256':runner.sha(I/'execution.json'),
               'observation_window_ms':1000,'market_entry_delay_ms':1000,'exit_delay_ms':5000,
               'fee_per_side':0.0005,'adverse_slippage_per_side':0.0005,'take_profit_r':2,
               'note':'One-second observation and entry; original precheck time buffer and risk proxy retained.'}
    (OUT/'逐笔执行冻结方案.json').write_text(json.dumps(execution,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_BATCH',year,json.dumps({k:v for k,v in quality.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
