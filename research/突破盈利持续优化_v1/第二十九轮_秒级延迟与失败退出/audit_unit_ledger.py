"""Recalculate opportunity ledgers from normalized mark/funding files independently."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
M=60_000

def near(a,b):return abs(float(a)-float(b)) <= 1e-10*max(1.,abs(float(a)),abs(float(b)))

def main():
    d=pd.read_parquet(HERE/'秒级净收益与风险核算.parquet')
    sel=pd.read_parquet(HERE/'事前条件通过候选.parquet')
    plan=json.loads((HERE/'冻结研究计划.json').read_text(encoding='utf-8'))
    assert len(d)==4*len(sel) and not d.duplicated(['observation_id','variant']).any()
    # Load source files directly, instead of reusing the research engine's market API.
    checked=0;funding_events=0;max_error=0.;proxy=0
    for (year,contract),g in d.groupby(['source_year','contract']):
        path=ROOT/'work'/('breakout_2024_expanded18' if str(year)=='2024' else 'breakout_november_2026')/'normalized'
        mark=pd.read_parquet(path/f'{contract}_markPriceKlines.parquet').set_index('ts')
        funds=pd.read_parquet(path/f'{contract}_fundingRate.parquet').sort_values('ts')
        assert mark.index.is_unique and not funds.ts.duplicated().any()
        ftime=funds.ts.to_numpy(np.int64);rates=funds.last_funding_rate.to_numpy(float)
        for r in g.itertuples(index=False):
            assert r.status=='verified' and r.risk_status=='verified'
            assert r.entry_ts>=r.decision_ts+10_000 and r.exit_ts>=r.exit_signal_ts+5_000
            assert r.exit_ts>=r.entry_ts and r.exit_signal_ts<=r.quarter_end
            side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005)
            assert near(entry,r.entry_fill) and near(exit,r.exit_fill)
            qty=1/entry;pay=0.
            a=np.searchsorted(ftime,r.entry_ts,side='left');b=np.searchsorted(ftime,r.exit_ts,side='right')
            for k in range(a,b):
                t=int(ftime[k]);opening=float(mark.loc[t//M*M,'open'])
                amount=side*qty*opening*float(rates[k])
                pay+=max(0.,amount) if t in (r.entry_ts,r.exit_ts) else amount
                funding_events+=1
            assert near(pay,r.funding)
            fee0=.0005;fee1=.0005*qty*exit
            net=side*qty*(exit-entry)-fee0-fee1-pay
            assert near(fee0,r.entry_fee) and near(fee1,r.exit_fee)
            err=abs(net-float(r.net_per_unit_notional));max_error=max(max_error,err)
            assert near(net,r.net_per_unit_notional) and near(100*net,r.net_pct_notional)
            minute_list=np.arange(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M,dtype=np.int64)
            z=mark.reindex(minute_list);assert z[['open','high','low','close']].notna().all().all()
            extreme=z['low' if side==1 else 'high'].to_numpy(float)
            threshold=qty*extreme*.01
            proxy_hit=bool(np.any(.05-.0005-max(pay,0.)+side*qty*(extreme-entry)<=threshold))
            assert proxy_hit==bool(r.liq_proxy);proxy+=int(proxy_hit);checked+=1
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    train=d[d.source_year.eq('2024')&(d.quarter_end+M<=cutoff)]
    if (HERE/'秒级训练机会对照.json').exists():
        scores=json.loads((HERE/'秒级训练机会对照.json').read_text(encoding='utf-8'))
        for s in scores:
            x=train[train.variant.eq(s['variant'])].net_per_unit_notional.to_numpy(float)
            assert len(x)==s['events'] and int((x>0).sum())==s['net_wins']
            assert near(100*(x>0).mean(),s['net_win_rate_pct']) and near(x.sum(),s['sum_net_per_unit_notional'])
            assert near(x[x>0].sum()/-x[x<0].sum(),s['profit_factor'])
        dec=json.loads((HERE/'秒级冻结筛选决定.json').read_text(encoding='utf-8'))
        assert dec['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
        assert dec['train_sha256']==hashlib.sha256((HERE/'秒级训练机会对照.json').read_bytes()).hexdigest()
        viable=[x for x in scores if x['events']>=50]
        passed=[x for x in viable if x['net_win_rate_pct']>=60 and x['sum_net_per_unit_notional']>0 and x['profit_factor'] and x['profit_factor']>1]
        expected=max(passed or viable,key=lambda x:x['average_net_pct_notional']) if viable else None
        assert dec['selected']==(expected['variant'] if expected else None)
        assert dec['training_screen_passed']==bool(passed)
    result={'checked_opportunity_paths':checked,'distinct_opportunities':len(sel),'funding_events_recomputed':funding_events,
            'max_net_fraction_error':max_error,'liquidation_proxy_paths':proxy,'entry_exit_timing_and_fee':True,
            'entry_and_exit_slippage':True,'funding_recomputed_from_original_normalized':True,
            'minute_mark_risk_recomputed_independently':True,'train_end_uses_clock_embargo':True,
            'frozen_train_selection_checked':(HERE/'秒级冻结筛选决定.json').exists(),
            'scope':'Historical unit paths only; no shared-account or actual fill validation.'}
    (HERE/'秒级净账本独立核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('SECONDS29_LEDGER_AUDIT',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
