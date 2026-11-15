"""Compare market and conditional Post-Only fills on matched independent orders."""
import importlib.util,json,sys
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'突破胜率与净收益前瞻检验_v1'
WORK=HERE.parent.parent/'work'/'breakout_maker_tapes_2026'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
forward=load('maker_execution_context',PRIOR/'forward_research.py')
sim=load('maker_order_engine',HERE/'sim_order.py')
market=forward.FixedMarket()
signals=pd.read_parquet(HERE/'计划下单候选.parquet')
manifest=json.loads((HERE/'逐笔成交数据校验.json').read_text(encoding='utf-8'))
lookup={(r['contract'],r['day']):r for r in manifest['records']}
DAY=86_400_000;END=1793491200000

@lru_cache(maxsize=64)
def day_tape(contract,day):return pd.read_parquet(WORK/'tapes'/f'{contract}_{day}.parquet')

def tape_for(s):
    start=int(s.ts)-30_000;end=min(int(s.ts)+63*60_000+5_000,END)
    pieces=[];day=start//DAY*DAY
    while day<end:
        tag=pd.Timestamp(day,unit='ms',tz='UTC').strftime('%Y-%m-%d')
        if lookup.get((s.contract,tag),{}).get('status')!='verified':return None
        pieces.append(day_tape(s.contract,tag));day+=DAY
    t=pd.concat(pieces,ignore_index=True)
    t=t[(t.transact_time>=start)&(t.transact_time<end)].sort_values(['transact_time','agg_trade_id'])
    if t.agg_trade_id.duplicated().any():raise ValueError('Duplicated aggregate trade ID in window')
    return (t.transact_time.to_numpy('int64'),t.price.to_numpy(float),
            t.quantity.to_numpy(float),t.is_buyer_maker.to_numpy(bool))

def main():
    outcomes=[];plans=[]
    variants=[('market_2r','market',2.,0),('limit_q0_2r','limit',2.,0),
              ('limit_q10_2r','limit',2.,10),('limit_q100_2r','limit',2.,100),
              ('market_1r','market',1.,0),('limit_q0_1r','limit',1.,0),
              ('limit_q10_1r','limit',1.,10),('limit_q100_1r','limit',1.,100)]
    for n,s in enumerate(signals.itertuples(index=False),1):
        tape=tape_for(s)
        if tape is None:
            plans.append({'observation_id':s.observation_id,'status':'archive_unknown'});continue
        plan,status=sim.make_plan(s,market,tape[0],tape[1])
        if plan is None:
            plans.append({'observation_id':s.observation_id,'status':status});continue
        plans.append(dict(plan,status='ready'))
        for name,method,target,queue in variants:
            result=sim.run_order(plan,*tape,method,target,queue,market)
            result['variant']=name;result['signal_ts']=int(s.ts)
            outcomes.append(result)
        if n%10==0:print('ORDERS_REPLAYED',n,'/',len(signals),flush=True)
    df=pd.DataFrame(outcomes);plans_df=pd.DataFrame(plans)
    plans_df.to_parquet(HERE/'逐信号计划与状态.parquet',index=False)
    df.to_parquet(HERE/'逐信号订单模拟.parquet',index=False)
    known_zero={'unfilled_expired','not_submitted_entry_deviation','not_submitted_stop_cost','not_submitted_after_quarter'}
    rows=[]
    for name,g in df.groupby('variant',sort=False):
        filled=g[g.status.eq('filled')];zero=g[g.status.isin(known_zero)]
        known=pd.concat([filled,zero]).copy()
        if len(known):
            net=pd.to_numeric(known.net,errors='coerce').fillna(0)
            # Explicitly treat only genuinely known no-fill/no-entry outcomes as zero.
            norm=np.where(known.status.eq('filled'),net/known.planned_notional*10000,0.)
            avg_u=float(net.mean());avg_bp=float(np.mean(norm))
        else:avg_u=None;avg_bp=None
        rows.append({'variant':name,'common_plans':len(g),'known_outcomes':len(known),
          'unknown_outcomes':len(g)-len(known),'orders_filled_any':len(filled),
          'orders_fully_filled':int((filled.fill_fraction>=1-1e-10).sum()),
          'orders_partially_filled':int((filled.fill_fraction<1-1e-10).sum()),
          'orders_initially_partial':int((filled.first_fill_fraction<1-1e-10).sum()),
          'orders_with_assumed_price_through':int((filled.qty_assumed_through>0).sum()),
          'orders_through_and_stop_same_tick':int(filled.assumed_through_stop_same_tick.sum()),
          'unfilled_expired':int(g.status.eq('unfilled_expired').sum()),
          'not_submitted':int(g.status.str.startswith('not_submitted').sum()),
          'fill_rate_of_known_pct':100*len(filled)/len(known) if len(known) else None,
          'net_wins':int((filled.net>0).sum()),'filled_net_win_pct':100*(filled.net>0).mean() if len(filled) else None,
          'mean_net_u_per_common_opportunity':avg_u,'mean_net_bp_per_planned_notional':avg_bp,
          'mean_net_u_per_filled_order':float(filled.net.mean()) if len(filled) else None,
          'mean_fill_fraction_given_fill':float(filled.fill_fraction.mean()) if len(filled) else None,
          'median_first_fill_delay_seconds':float(((filled.first_fill_ts-filled.submit_ts)/1000).median()) if len(filled) else None})
    summary=pd.DataFrame(rows);summary.to_csv(HERE/'挂单与吃单机会对照.csv',index=False,encoding='utf-8-sig')
    data={'eligible_before_trade_tape':len(signals),'common_plan_status_counts':plans_df.status.value_counts().to_dict(),
          'order_status_counts':{v:g.status.value_counts().to_dict() for v,g in df.groupby('variant')},
          'interpretation':'Independent matched opportunities, not a simultaneous account. Limit results are conditional on unverified Post-Only acceptance and assumed queue.'}
    (HERE/'订单执行状态汇总.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('MAKER_REPLAY_COMPLETE',json.dumps(data,ensure_ascii=False),flush=True)
    print(summary.to_string(index=False),flush=True)
if __name__=='__main__':main()
