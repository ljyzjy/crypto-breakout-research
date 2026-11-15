"""Synthetic tests for paired 1R timing, slippage and source disagreement."""
import hashlib,json
from pathlib import Path
import pandas as pd
from exit_1r import decide
H=Path(__file__).resolve().parent
def tape(items):return pd.DataFrame({'transact_time':[x[0] for x in items],'price':[x[1] for x in items]})
def main():
    e={'side':1,'quarter_end':60000,'entry_exec_ts':5000,'raw_entry_5s':100.}
    entry=100.1*1.0005
    old={'status':'verified','entry_ts':10000,'entry_raw':100.1,'entry_fill':entry,'initial_stop':99.65,
         'exit_signal_ts':25000,'exit_ts':30000,'exit_raw':101.1,'reason':'target'}
    x=tape([(5000,100.),(10000,100.1),(15000,100.7),(20000,100.6),(25000,101.2),(30000,101.1),(65000,101.)])
    one=decide(e,old,x);assert one['status']=='verified' and one['reason']=='target' and one['exit_signal_ts']==15000 and one['exit_ts']==20000
    assert abs(one['exit_fill']-100.6*.9995)<1e-12 and one['target_r']==1.
    stopold={**old,'exit_signal_ts':15000,'exit_ts':20000,'exit_raw':99.7,'reason':'stop'}
    stop=tape([(5000,100.),(10000,100.1),(15000,99.6),(20000,99.7),(65000,99.8)])
    y=decide(e,stopold,stop);assert y['status']=='verified' and y['reason']=='stop' and y['exit_signal_ts']==15000
    clockold={**old,'exit_signal_ts':60000,'exit_ts':65000,'exit_raw':100.2,'reason':'quarter_time'}
    clock=tape([(5000,100.),(10000,100.1),(20000,100.2),(60000,100.2),(65000,100.2)])
    assert decide(e,clockold,clock)['reason']=='quarter_time'
    invalid={**old,'initial_stop':100.3,'exit_signal_ts':10000,'exit_ts':15000,'exit_raw':100.7,'reason':'filled_beyond_risk_budget'}
    bad=decide(e,invalid,x);assert bad['status']=='verified' and bad['reason']=='filled_beyond_risk_budget' and bad['exit_ts']==15000
    tieold={**old,'exit_signal_ts':15000,'exit_ts':20000,'exit_raw':100.6,'reason':'stop'}
    tie=tape([(5000,100.),(10000,100.1),(15000,100.7),(15000,99.6),(20000,100.6),(65000,100.)])
    assert decide(e,tieold,tie)['reason']=='stop'
    shifted=x.copy();shifted.loc[shifted.transact_time.eq(20000),'price']=100.4
    assert decide(e,old,shifted)['exit_signal_ts']==one['exit_signal_ts']
    wrong={**old,'entry_raw':123.};assert decide(e,wrong,x)['status']=='entry_disagreement'
    out={'all_checks_pass':True,'same_entry_and_delayed_exit_checked':True,'stop_and_clock_checked':True,
         'risk_budget_breach_still_filled':True,'same_time_stop_priority_checked':True,
         'future_price_perturbation_checked':True,'source_disagreement_unknown':True,
         'code_sha256':hashlib.sha256((H/'exit_1r.py').read_bytes()).hexdigest()}
    (H/'一倍止盈合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_SYNTHETIC',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
