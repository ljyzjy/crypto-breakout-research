"""Synthetic causal, single-retry, delayed-fill and source-conflict checks."""
import hashlib,json
from pathlib import Path
import pandas as pd
from retest_decision import decide
H=Path(__file__).resolve().parent
def frame(extra):
    rows=[(1000,100.1,'false'),(2000,100.05,'true'),(3000,100.05,'true'),(4000,100.05,'true'),(6000,99.95,'true'),(9000,99.9,'true')]+extra
    rows=sorted(rows,key=lambda x:x[0])
    return pd.DataFrame({'agg_trade_id':range(len(rows)),'transact_time':[x[0] for x in rows],
                         'price':[x[1] for x in rows],'quantity':[1.]*len(rows),'is_buyer_maker':[x[2] for x in rows]})
def event():return {'status':'flow_filter_not_met','side':1,'level':100.,'upper':100.,'lower':98.,'quarter_end':900_000,
    'trigger_minute':0,'decision_ts':1000,'signal_close':100.1,'entry_exec_ts':6000,'raw_entry_5s':99.95,
    'five_count':3,'buy_notional':0.,'sell_notional':300.15,'five_imbalance':-1.,'stop_price':99.5,'atr':1.}
def main():
    no=decide(event(),frame([(10000,99.8,'true'),(905000,99.7,'true')]))
    assert no['status']=='no_retest_known'
    extra=[(10000,100.1,'false'),(11000,100.1,'false'),(12000,100.1,'false'),(13000,100.1,'false'),
           (15000,100.2,'false'),(20000,100.25,'false'),(30000,102.,'false'),(35000,101.95,'true')]
    good=decide(event(),frame(extra));assert good['status']=='qualified' and good['retest_ts']==10000
    assert set(good['paths'])=={'normal_2r_10x','normal_2r_20x'}
    for p in good['paths'].values():assert p['entry_ts']==20000 and p['exit_signal_ts']==30000 and p['exit_ts']==35000 and p['reason']=='target'
    late=frame(extra);late.loc[late.transact_time.eq(30000),'price']=100.5
    alternative=decide(event(),late)
    assert (alternative['retest_ts'],alternative['entry_exec_ts'],alternative['five_count'],alternative['prechecks'])==(good['retest_ts'],good['entry_exec_ts'],good['five_count'],good['prechecks'])
    once=frame([(10000,100.1,'false'),(11000,100.1,'false'),(12000,100.1,'false'),(13000,100.1,'false'),
                (15000,99.9,'true'),(20000,100.1,'false'),(21000,100.1,'false'),(22000,100.1,'false'),(23000,100.1,'false'),(25000,100.2,'false')])
    assert decide(event(),once)['status']=='retest_flow_filter_not_met'
    broken=event();broken['sell_notional']=1.;assert decide(broken,frame(extra))['status']=='original_first_stage_disagreement'
    bad=frame(extra);bad.loc[bad.transact_time.eq(20000),'price']=99.4
    risk=decide(event(),bad);assert risk['status']=='qualified'
    for p in risk['paths'].values():assert p['reason']=='filled_beyond_risk_budget' and p['exit_ts']>=p['entry_ts']+5000
    out={'all_checks_pass':True,'no_retest_checked':True,'successful_delayed_entry_exit_checked':True,
         'future_outcome_perturbation_checked':True,'only_one_retest_checked':True,
         'source_disagreement_unknown':True,'risk_budget_breach_still_filled':True,
         'decision_code_sha256':hashlib.sha256((H/'retest_decision.py').read_bytes()).hexdigest()}
    (H/'一次重试合成时序核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_SYNTHETIC',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
