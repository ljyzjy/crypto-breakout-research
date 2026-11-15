"""Compare one-second entries with 1R versus 2R on the same known units."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
def stats(v,u):
    x=np.array(v,float);assert np.isfinite(x).all();n=len(x);w=int((x>0).sum());loss=-float(x[x<0].sum())
    return {'trades':n,'wins':w,'net_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(x.mean()) if n else None,
            'profit_factor':float(x[x>0].sum())/loss if loss else None,'optimistic_unit_win_upper_pct':100*(w+u)/(n+u) if n+u else None}
def main(year):
    I=H/f'{year}冻结输入';B=H/f'{year}一秒一倍分批';base=pd.read_parquet(I/'ledger_2r.parquet');new=pd.read_parquet(B/'动态池单位收益与风险.parquet')
    ref=json.loads((I/'pair_summary.json').read_text(encoding='utf-8'))['rows'];refids=pd.read_parquet(I/'pair_details.parquet');rows=[];details=[]
    for lev in (10,20):
        x=next(r for r in ref if r['leverage']==lev); ids=set(refids.loc[refids.leverage.eq(lev),'observation_id']);assert len(ids)==x['paired_verified']
        old=base[base.variant.eq(f'one_second_2r_{lev}x')].set_index('observation_id')
        now=new[new.variant.eq(f'one_second_1r_{lev}x')].set_index('observation_id') if len(new) else pd.DataFrame()
        pairs=[];unresolved=[]
        for obs in sorted(ids):
            a=old.loc[obs];assert a.risk_status=='verified' and not a.liq_proxy
            if obs not in now.index:unresolved.append(obs);continue
            b=now.loc[obs]
            if b.risk_status!='verified' or bool(b.liq_proxy):unresolved.append(obs);continue
            assert int(a.entry_ts)==int(b.entry_ts) and abs(float(a.entry_fill)-float(b.entry_fill))<1e-10 and int(b.exit_ts)<=int(a.exit_ts)
            pairs.append((obs,a,b));details.append({'observation_id':obs,'leverage':lev,'one_r_net':float(b.net_per_unit_notional),
                'two_r_net':float(a.net_per_unit_notional),'entry_ts':int(a.entry_ts),'one_r_reason':b.reason,'two_r_reason':a.reason})
        n=len(pairs);u=int(x['paired_unknown'])+len(unresolved);assert n+u+int(x['known_no_order'])==int(x['candidate_events'])
        one=[float(b.net_per_unit_notional) for _,a,b in pairs];two=[float(a.net_per_unit_notional) for _,a,b in pairs]
        diff=np.asarray(one)-np.asarray(two);days={pd.Timestamp(int(a.entry_ts),unit='ms',tz='UTC').date() for _,a,b in pairs}
        rows.append({'leverage':lev,'candidate_events':x['candidate_events'],'known_no_order':x['known_no_order'],'paired_verified':n,
            'paired_unknown':u,'original_unknown':x['paired_unknown'],'new_pending':len(unresolved),'active_days_utc':len(days),
            'one_r':stats(one,u),'two_r':stats(two,u),'one_r_better_count':int((diff>1e-12).sum()),
            'one_r_worse_count':int((diff< -1e-12).sum()),'same_count':int((np.abs(diff)<=1e-12).sum()),'pending_ids':unresolved})
    pd.DataFrame(details).to_parquet(H/f'{year}一秒一倍两倍逐笔配对.parquet',index=False)
    out={'year':year,'rows':rows,'note':'Same one-second entries, 1R and 2R exits; known unit paths only, not an account.'}
    (H/f'{year}一秒一倍两倍配对对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY1R58_PAIRED',year,json.dumps({'rows':[{k:v for k,v in r.items() if k!='pending_ids'} for r in rows]},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
