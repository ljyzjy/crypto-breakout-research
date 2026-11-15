"""Synthetic timing, direction, invalid-fill and tie cases for the 1s signal."""
import hashlib,json
from pathlib import Path
import pandas as pd
from one_second_observation import decide
H=Path(__file__).resolve().parent
def event(side):
    long={'stop_price':99.6,'level':100.,'score':1.,'rvol':2.,'rank':1,'liquidity_rank':1}
    short={'stop_price':100.4,'level':100.,'score':-1.,'rvol':2.,'rank':1,'liquidity_rank':1}
    return {'trigger_minute':0,'quarter_start':0,'quarter_end':60000,'upper':100. if side==1 else 110.,
            'lower':90. if side==1 else 100.,'atr':2.,'long_known_eligible':side==1,'short_known_eligible':side==-1,
            'long_spec':json.dumps(long),'short_spec':json.dumps(short)}
def data(items,side=1):
    d=pd.DataFrame([{'transact_time':t,'price':p if side==1 else 200-p,'quantity':1.,
                     'is_buyer_maker':'false' if side==1 else 'true'} for t,p in items])
    b=pd.DataFrame([{'open':d.price.iloc[0],'high':d.price.max(),'low':d.price.min(),'close':d.price.iloc[-1]}],index=[0])
    return d,b
def main():
    items=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(900,100.1),(1100,100.2),(2100,100.25),(5000,101.8),(10000,101.75)]
    d,b=data(items);out=decide(event(1),d,b);assert out['status']=='qualified' and out['one_count']==3
    assert out['decision_ts']==100 and out['entry_exec_ts']==1100 and all(v=='passed' for v in out['prechecks'].values())
    for v in out['paths'].values():assert v['status']=='verified' and v['entry_ts']==2100 and v['reason']=='target' and v['exit_ts']==10000
    d,b=data(items,-1);short=decide(event(-1),d,b);assert short['status']=='qualified' and short['side']==-1
    for v in short['paths'].values():assert v['status']=='verified' and v['reason']=='target' and v['entry_ts']==2100 and v['exit_ts']==10000
    tie=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(900,100.1),(1100,100.2),(2100,100.25),(5000,101.8),(5000,99.5),(10000,100.)]
    d,b=data(tie);out=decide(event(1),d,b);assert all(v['reason']=='stop' and v['exit_signal_ts']==5000 for v in out['paths'].values())
    breach=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(900,100.1),(1100,100.2),(2100,101.0),(10000,100.)]
    d,b=data(breach);out=decide(event(1),d,b);assert all(v['reason']=='filled_beyond_risk_budget' and v['exit_signal_ts']==2100 for v in out['paths'].values())
    missing=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(1100,100.2),(2100,100.25),(10000,100.)]
    d,b=data(missing);assert decide(event(1),d,b)['status']=='flow_filter_not_met'
    altered=items[:-2]+[(5000,100.4),(10000,100.3)];d1,b1=data(items);d2,b2=data(altered)
    a=decide(event(1),d1,b1);c=decide(event(1),d2,b2)
    for k in ('status','side','decision_ts','signal_close','entry_exec_ts','raw_entry_1s','one_count','buy_notional','sell_notional','one_imbalance','prechecks'):
        assert a[k]==c[k]
    record={'all_checks_pass':True,'long_short':True,'strict_window':True,'one_second_observation_and_entry':True,
            'same_millisecond_stop_priority':True,'filled_outside_budget':True,'future_perturbation':True,
            'code_sha256':hashlib.sha256((H/'one_second_observation.py').read_bytes()).hexdigest(),
            'plan_sha256':hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()}
    (H/'一秒观察合成时序核验.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_SYNTHETIC_PASS',json.dumps(record,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
