"""Independently reconstruct prior BTC/ETH conditions and selected unit outcomes."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';Q=900_000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    out=json.loads((H/'双币活跃度训练诊断.json').read_text(encoding='utf-8'))
    s=pd.read_parquet(I/'baseline_signal.parquet').to_dict('records');l=pd.read_parquet(I/'baseline_ledger.parquet').to_dict('records')
    db={(r.symbol,int(r.open_time)):r for r in pd.read_parquet(H/'BTC_ETH过去十五分钟数据.parquet').itertuples(index=False)}
    samples=json.loads((H/'BTC_ETH一分钟样本核验.json').read_text(encoding='utf-8'))
    suspect={(r['symbol'],int(r['open_time'])) for r in samples['samples'] if r['status']!='verified'}
    recorded=pd.read_parquet(H/'候选事前市场过滤.parquet').set_index('observation_id');decisions={};checks=0
    for e in s:
        quarter=int(e['quarter_start']);items=[]
        for sym in ('BTCUSDT','ETHUSDT'):
            history=[db.get((sym,quarter-i*Q)) if (sym,quarter-i*Q) not in suspect else None for i in range(21,0,-1)]
            if any(r is None or r.volume<=0 or r.count<=0 or r.open<=0 or r.close<=0 for r in history):items.append(('unknown',0));continue
            n=int(history[-1].count);p=sum(int(r.count) for r in history[:-1]);last=history[-1]
            side=1 if last.close>last.open else -1 if last.close<last.open else 0
            items.append(('rejected',0) if p>0 and (40*n<3*p or side==0) else ('passed',side) if p>0 else ('unknown',0))
        if any(x[0]=='rejected' for x in items):status='known_no_order';direction=0
        elif any(x[0]=='unknown' for x in items):status='market_unknown';direction=0
        elif items[0][1]!=items[1][1]:status='known_no_order';direction=0
        else:status='allowed';direction=items[0][1]
        got=recorded.loc[e['observation_id']];assert got.market_status==status and int(got.allowed_side)==direction
        decisions[e['observation_id']]=(status,direction);checks+=1
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    groups=[];maximum_error=0.
    for result in out['rows']:
        lev=result['leverage'];paths={x['observation_id']:x for x in l if x['variant']==f'normal_2r_{lev}x'}
        good={};unknown=set();rejected_count=0
        for e in s:
            obs=e['observation_id'];status,side=decisions[obs]
            if status=='known_no_order':rejected_count+=1;continue
            if e['status'] not in benign:
                eligible=(status=='market_unknown' or side==1 and e['long_known_eligible'] or side==-1 and e['short_known_eligible'])
                if eligible:unknown.add(obs)
                else:rejected_count+=1
                continue
            if e['status']!='qualified':rejected_count+=1;continue
            pre=e[f'precheck_{lev}x']
            if pd.isna(pre):unknown.add(obs);continue
            if pre!='passed':rejected_count+=1;continue
            if status=='market_unknown':unknown.add(obs);continue
            if int(e['side'])!=side:rejected_count+=1;continue
            r=paths.get(obs)
            if r is None or r['status']!='verified' or r['risk_status']!='verified' or r['liq_proxy']:unknown.add(obs);continue
            order=int(r['side']);en=float(r['entry_raw'])*(1+order*.0005);ex=float(r['exit_raw'])*(1-order*.0005)
            net=order*(ex/en-1)-.0005-.0005*ex/en-float(r['funding'])
            maximum_error=max(maximum_error,abs(net-float(r['net_per_unit_notional'])));assert near(net,r['net_per_unit_notional'])
            assert int(r['entry_ts'])>=int(r['decision_ts'])+10000;good[obs]=net
        vals=list(good.values());wins=sum(v>0 for v in vals);n=len(vals);u=len(unknown)
        assert set(result['verified_observation_ids'])==set(good) and set(result['unknown_observation_ids'])==unknown
        assert result['known_no_order_events']==rejected_count and result['verified_events']==n and result['verified_wins']==wins
        if n:
            assert near(result['verified_win_rate_pct'],100*wins/n) and near(result['mean_net_pct_notional'],100*sum(vals)/n)
            pos=sum(v for v in vals if v>0);neg=-sum(v for v in vals if v<0)
            if neg:assert near(result['profit_factor'],pos/neg)
        if n+u:assert near(result['unit_win_rate_upper_pct'],100*(wins+u)/(n+u))
        assert n+u+rejected_count==len(s)
        groups.append({'leverage':lev,'verified':n,'wins':wins,'unknown':u,'known_no_order':rejected_count})
    costfile=H/'双币过滤成本分解.json';cost_verified=False
    if costfile.exists():
        c=json.loads(costfile.read_text(encoding='utf-8'))
        for z in c['rows']:
            base=next(x for x in out['rows'] if x['leverage']==z['leverage']);ids=set(base['verified_observation_ids'])
            rows=[r for r in l if r['variant']==f"normal_2r_{z['leverage']}x" and r['observation_id'] in ids]
            assert len(rows)==len(ids)==z['verified_events'];n=len(rows)
            gross=sum(r['side']*(r['exit_raw']-r['entry_raw'])/r['entry_fill'] for r in rows)/n*100
            slip=sum(r['side']*((r['exit_fill']-r['exit_raw'])-(r['entry_fill']-r['entry_raw']))/r['entry_fill'] for r in rows)/n*100
            fee=-sum(r['entry_fee']+r['exit_fee'] for r in rows)/n*100;fund=-sum(r['funding'] for r in rows)/n*100
            assert near(z['mean_raw_price_movement_pct_notional'],gross) and near(z['mean_slippage_pct_notional'],slip)
            assert near(z['mean_fees_pct_notional'],fee) and near(z['mean_funding_pct_notional'],fund)
            assert near(gross+slip+fee+fund,z['mean_net_pct_notional'])
            assert z['exit_reasons']=={reason:sum(r['reason']==reason for r in rows) for reason in set(r['reason'] for r in rows)}
        cost_verified=True
    audit={'candidate_market_decisions_checked':checks,'groups':groups,'maximum_net_fraction_error':maximum_error,
           'sample_ohlc_and_trade_counts_verified':samples['sample_verified'],'all_checks_pass':True,
           'cost_decomposition_checked':cost_verified,
           'note':'No account concurrency or realized broker fills reconstructed; prior source checks and unknowns persist.'}
    (H/'双币活跃度独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL42_AUDIT',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
