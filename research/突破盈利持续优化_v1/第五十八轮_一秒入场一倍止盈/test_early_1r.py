"""Synthetic timing and direction tests for the frozen one-second/1R rule."""
import hashlib,json
from pathlib import Path
import pandas as pd
from early_1r import decide
H=Path(__file__).resolve().parent
def tape(items):return pd.DataFrame({'transact_time':[x[0] for x in items],'price':[x[1] for x in items]})
def main():
    e={'side':1,'quarter_end':60000,'entry_exec_ts':5000,'raw_entry_5s':100.}
    entry=100.1*1.0005
    old={'status':'verified','entry_ts':6000,'entry_raw':100.1,'entry_fill':entry,'initial_stop':99.65,
         'exit_signal_ts':25000,'exit_ts':30000,'exit_raw':101.1,'reason':'target'}
    x=tape([(5000,100.),(6000,100.1),(15000,100.7),(20000,100.6),(25000,101.2),(30000,101.1),(65000,101.)])
    a=decide(e,old,x);assert a['status']=='verified' and a['reason']=='target' and a['exit_signal_ts']==15000 and a['exit_ts']==20000
    assert abs(a['exit_fill']-100.6*.9995)<1e-12 and a['entry_ts']==6000 and a['target_r']==1.
    se={**e,'side':-1}; so={**old,'entry_raw':99.9,'entry_fill':99.9*.9995,'initial_stop':100.35,'exit_raw':98.9}
    sx=tape([(5000,100.),(6000,99.9),(15000,99.3),(20000,99.4),(25000,98.8),(30000,98.9),(65000,99.)])
    b=decide(se,so,sx);assert b['status']=='verified' and b['reason']=='target' and b['exit_signal_ts']==15000 and abs(b['exit_fill']-99.4*1.0005)<1e-12
    tieold={**old,'exit_signal_ts':15000,'exit_ts':20000,'exit_raw':100.6,'reason':'stop'}
    tie=tape([(5000,100.),(6000,100.1),(15000,100.7),(15000,99.6),(20000,100.6),(65000,100.)])
    assert decide(e,tieold,tie)['reason']=='stop'
    breach={**old,'initial_stop':100.3,'exit_signal_ts':6000,'exit_ts':11000,'exit_raw':100.7,'reason':'filled_beyond_risk_budget'}
    bt=tape([(5000,100.),(6000,100.1),(11000,100.7),(65000,100.)]);c=decide(e,breach,bt)
    assert c['status']=='verified' and c['reason']=='filled_beyond_risk_budget' and c['exit_ts']==11000
    wrong={**old,'entry_raw':123.};assert decide(e,wrong,x)['status']=='entry_disagreement'
    future=x.copy();future.loc[future.transact_time.eq(20000),'price']=100.4
    assert decide(e,old,future)['exit_signal_ts']==a['exit_signal_ts']
    out={'all_checks_pass':True,'long_and_short':True,'one_second_entry':True,'five_second_exit':True,
         'same_millisecond_stop_priority':True,'risk_budget_breach_filled':True,'source_mismatch_rejected':True,
         'future_price_perturbation':True,'code_sha256':hashlib.sha256((H/'early_1r.py').read_bytes()).hexdigest(),
         'plan_sha256':hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()}
    (H/'组合合成时序核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY_1R_SYNTHETIC_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
