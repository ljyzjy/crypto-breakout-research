"""Independent market-gate, ledger, accounting and missingness reconciliation."""
import json,math,hashlib
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;Q=900_000;M=60_000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    source=pd.read_parquet(H/'冻结输入'/'baseline_signal.parquet').to_dict('records')
    bars=pd.read_parquet(H/'BTC_ETH过去十五分钟数据.parquet')
    bybar={(r.symbol,int(r.open_time)):r for r in bars.itertuples(index=False)}
    sample=json.loads((H/'BTC_ETH一分钟样本核验.json').read_text(encoding='utf-8'))
    suspect={(r['symbol'],int(r['open_time'])) for r in sample['samples'] if r['status']!='verified'}
    recorded=pd.read_parquet(H/'候选事前市场过滤.parquet').set_index('observation_id');decisions={}
    for e in source:
        q=int(e['quarter_start']);items=[]
        for sym in ('BTCUSDT','ETHUSDT'):
            hist=[bybar.get((sym,q-i*Q)) if (sym,q-i*Q) not in suspect else None for i in range(21,0,-1)]
            if any(x is None or x.volume<=0 or x.count<=0 or x.open<=0 or x.close<=0 for x in hist):items.append(('unknown',0));continue
            n=int(hist[-1].count);p=sum(int(x.count) for x in hist[:-1]);end=hist[-1]
            side=1 if end.close>end.open else -1 if end.close<end.open else 0
            items.append(('unknown',0) if p<=0 else ('rejected',0) if 40*n<3*p or side==0 else ('passed',side))
        if any(x[0]=='rejected' for x in items):status,side='known_no_order',0
        elif any(x[0]=='unknown' for x in items):status,side='market_unknown',0
        elif items[0][1]!=items[1][1]:status,side='known_no_order',0
        else:status,side='allowed',items[0][1]
        got=recorded.loc[e['observation_id']]
        assert got.market_status==status and int(got.allowed_side)==side
        decisions[e['observation_id']]=(status,side)
    report=json.loads((H/'跨时段双币过滤诊断.json').read_text(encoding='utf-8'))
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_cross44';benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    result=[];total_paths=0;maxerr=0.
    for period in ('2024_may_jun','2026_may_jul'):
        d=H/period;ledger=pd.read_parquet(d/'动态池单位收益与风险.parquet').to_dict('records')
        manifest=json.loads((d/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
        expected={(r['kind'],r['contract'],r['month']):r for r in manifest}
        marks={};funds={};matched=set()
        for path in cache.glob('*.json'):
            rec=json.loads(path.read_text(encoding='utf-8'));key=(rec['kind'],rec['contract'],rec['month'])
            if key not in expected or rec['sha256']!=expected[key].get('sha256'):continue
            matched.add(key)
            if rec['kind']=='markPriceKlines':
                for row in rec['rows']:marks[(rec['contract'],int(row['ts']))]=row
            else:funds[(rec['contract'],rec['month'])]=rec['rows']
        assert len(matched)==sum(r['status']=='verified' for r in manifest)
        for r in ledger:
            if r['risk_status']!='verified':continue
            side=int(r['side']);entry=float(r['entry_raw'])*(1+side*.0005);exit=float(r['exit_raw'])*(1-side*.0005)
            assert near(entry,r['entry_fill']) and near(exit,r['exit_fill'])
            assert r['entry_ts']>=r['decision_ts']+10_000 and r['exit_ts']>=r['exit_signal_ts']+5_000
            qty=1/entry;charge=0.;events=[];adverse=[]
            for t in range(int(r['entry_ts'])//M*M,int(r['exit_ts'])//M*M+M,M):
                mark=marks[(r['contract'],t)];adverse.append(float(mark['low'] if side==1 else mark['high']))
                month=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m')
                for x in funds.get((r['contract'],month),[]):
                    ft=int(x['ts'])
                    if ft//M*M!=t or not r['entry_ts']<=ft<=r['exit_ts']:continue
                    z=side*qty*float(mark['open'])*float(x['last_funding_rate'])
                    charge+=max(0.,z) if ft in (r['entry_ts'],r['exit_ts']) else z;events.append(ft)
            assert near(charge,r['funding']) and sorted(events)==sorted(int(x['settlement_ts']) for x in json.loads(r['funding_events_json']))
            net=side*qty*(exit-entry)-.0005-qty*exit*.0005-charge
            assert near(r['entry_fee'],.0005) and near(r['exit_fee'],qty*exit*.0005) and near(net,r['net_per_unit_notional'])
            maxerr=max(maxerr,abs(net-r['net_per_unit_notional']))
            lev=int(r['variant'].rsplit('_',1)[1].rstrip('x'))
            hit=any(1/lev-.0005-max(charge,0.)+side*qty*(z-entry)<=qty*z*.01 for z in adverse)
            assert hit==bool(r['liq_proxy']);total_paths+=1
        s=[e for e in source if e['research_period']==period]
        for lev in (10,20):
            paths={r['observation_id']:r for r in ledger if r['variant']==f'normal_2r_{lev}x'}
            good={};unknown=set();noorder=0
            for e in s:
                obs=e['observation_id'];status,side=decisions[obs]
                if status=='known_no_order':noorder+=1;continue
                if e['status'] not in benign:
                    if status=='market_unknown' or side==1 and e['long_known_eligible'] or side==-1 and e['short_known_eligible']:unknown.add(obs)
                    else:noorder+=1
                    continue
                if e['status']!='qualified':noorder+=1;continue
                pre=e[f'precheck_{lev}x']
                if pd.isna(pre):unknown.add(obs);continue
                if pre!='passed':noorder+=1;continue
                if status=='market_unknown':unknown.add(obs);continue
                if int(e['side'])!=side:noorder+=1;continue
                r=paths.get(obs)
                if r is None or r['status']!='verified' or r['risk_status']!='verified' or r['liq_proxy']:unknown.add(obs);continue
                good[obs]=float(r['net_per_unit_notional'])
            z=next(x for x in report['rows'] if x['period']==period and x['leverage']==lev)
            n=len(good);u=len(unknown);w=sum(x>0 for x in good.values())
            assert n+u+noorder==len(s) and set(z['verified_observation_ids'])==set(good) and set(z['unknown_observation_ids'])==unknown
            assert z['known_no_order']==noorder and z['verified_events']==n and z['verified_wins']==w
            if n:assert near(z['verified_win_rate_pct'],100*w/n) and near(z['mean_net_pct_notional'],100*sum(good.values())/n)
            if n+u:assert near(z['unit_win_rate_upper_pct'],100*(w+u)/(n+u)) and near(z['unit_win_rate_lower_pct'],100*w/(n+u))
            result.append({'period':period,'leverage':lev,'verified':n,'wins':w,'unknown':u,'no_order':noorder})
    out={'market_decisions_checked':len(decisions),'independent_verified_ledger_paths':total_paths,'maximum_net_fraction_error':maxerr,
         'sample_ohlc_and_counts_verified':sample['sample_verified'],'groups':result,'all_checks_pass':True,
         'note':'Source and accounting reconciliation, not evidence of account execution or a blind test.'}
    (H/'跨时段独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
