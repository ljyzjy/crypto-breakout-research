"""Post-run correctness checks; no parameter search or selection changes."""
import hashlib,json
from datetime import datetime,timezone
import pandas as pd
import numpy as np
import pool_engine as p

def main():
    checks=[];frozen=p.old.base.read(p.ROOT/'frozen.json')
    for name,h in frozen.items():assert hashlib.sha256((p.ROOT/name).read_bytes()).hexdigest()==h,name
    manifest=p.old.base.read(p.ROOT/'execution-data-manifest.json')
    for name,h in manifest['old_hashes'].items():assert hashlib.sha256((p.OLD/name).read_bytes()).hexdigest()==h,name
    for name,h in manifest['processed'].items():assert hashlib.sha256((p.ROOT/'execution-data'/name).read_bytes()).hexdigest()==h,name
    checks.append('Frozen research rules, original data/source hashes, and expanded execution data hashes unchanged')
    rows=p.old.base.read(p.ROOT/'metrics.json');assert len(rows)==42
    factors=p.old.rankings()[0];count=0
    for row in rows:
        r=p.cached_run(row['start'],row['end'],row['mode'],row['fee'],row['resolution'],row['delay_minutes'])
        assert r['valid_for_comparison'] and r['open_positions']==0 and r['cash_min']>=0
        assert abs(1000+sum(t['pnl'] for t in r['trades'])-r['final_equity'])<1e-7
        assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-sum(t['pnl'] for t in r['trades']))<1e-7
        spec=p.VARIANTS[r['mode']];trace={x['date']:x for x in r['selection_trace']}
        for o in r['orders']:
            if o['information_ts'] is not None:assert o['information_ts']<=o['ts']
            if o['side']=='buy':
                info=pd.Timestamp(o['information_ts'],unit='s',tz='UTC')
                assert info.hour==0 and info.minute==0
                assert o['ts']==o['information_ts']+r['delay_minutes']*60
                tr=trace[info.strftime('%Y-%m-%d')]
                assert o['symbol'] in tr['selected'] and tr['market_allows_entry']
                assert pd.Timestamp(tr['information_through'],tz='UTC')+pd.Timedelta(days=1)<=info
        for t in r['trades']:
            day=pd.Timestamp(t['entry_ts']-r['delay_minutes']*60,unit='s',tz='UTC').normalize()-pd.Timedelta(days=1)
            f=factors[t['symbol']].loc[day];sigma=f['sigma']
            assert f['mom']>0 and f['valid']
            dist=float(np.clip(2*sigma,.04,.20)) if spec['volstop'] else .04
            amount=min(200,4/dist) if spec['volstop'] else min(200,2/sigma)
            assert abs(t['stop_distance']-dist)<1e-10 and abs(t['stake']-amount)<1e-9
            if spec['volstop']:assert t['planned_stop_loss']<=4+1e-9
            assert abs(t['fees']-r['fee']*t['qty']*(t['entry_price']+t['exit_price']))<1e-8
            if spec['retry'] and t['reason'] in ('gap_stop','stop_loss') and t['pnl']<0:
                mid=pd.Timestamp(t['exit_ts'],unit='s',tz='UTC').normalize()
                cutoff=int((mid+pd.Timedelta(days=7-mid.weekday())).timestamp())
                assert not any(o['side']=='buy' and o['symbol']==t['symbol'] and t['exit_ts']<=o['ts']<cutoff for o in r['orders'])
            count+=1
        if r['mode']=='pool_control':
            old=p.old.cached_run(r['start'],r['end'],'auto_budget2',r['fee'],r['resolution'],r['delay_minutes'])
            for field in ('curve','orders','return_pct','max_drawdown','fees','slippage_cost','cash_min','guard_activations'):assert r[field]==old[field],field
        print('verified',row['mode'],row['window'],row['fee'],row['resolution'],row['delay_minutes'],flush=True)
    checks.append(f'All42 fixed paths valid; {count} scenario-trades reconcile; known-day selection, sizing, costs, stop distance and next-week retry verified')
    checks.append('Seven original-control scenarios have identical orders, curve, fees, returns and drawdown')
    prefixes=[]
    for mode in ('pool_slow_selection','pool_combined'):
        full=p.cached_run('2025-01-01','2026-10-31',mode)
        for end in ('2025-06-30','2026-06-30'):
            short=p.simulate('2025-01-01',end,mode)
            boundary=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
            keep=lambda r:[o for o in r['orders'] if o['ts']<boundary and o['reason']!='window_end']
            assert keep(short)==keep(full),(mode,end)
            assert short['selection_trace']==[t for t in full['selection_trace'] if t['date']<=end]
            prefixes.append({'mode':mode,'end':end,'orders':len(keep(short)),'passed':True})
            print('prefix passed',mode,end,flush=True)
    checks.append('Two actual-data prefix cutoffs for both candidates preserve all prior orders and selected sets; administrative end liquidation excluded')
    preflight=p.old.base.read(p.ROOT/'preflight-validation.json');assert preflight['passed']
    result={'passed':True,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scenarios':42,'scenario_trades_checked':count,'checks':checks,'prefixes':prefixes,'preflight':preflight,
            'limits':['These checks test implementation causality and ledger integrity, not independent out-of-sample predictive value.','Historical data snapshots and exclusion metadata may be revised by publisher.','Drawdown is execution-bar closing marked; no assurance of an intrabar or future15percent maximum.','Current paper strategy and independent forward observer are not changed.']}
    p.old.base.dump(p.ROOT/'validation.json',result)
    print(json.dumps({'passed':True,'scenarios':42,'scenario_trades':count,'prefixes':prefixes}))

if __name__=='__main__':main()
