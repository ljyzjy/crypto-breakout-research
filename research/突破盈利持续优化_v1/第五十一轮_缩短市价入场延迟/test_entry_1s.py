"""Synthetic causal, long/short, risk and conservative tie tests."""
import hashlib,json
from pathlib import Path
import pandas as pd
import entry_1s
H=Path(__file__).resolve().parent
def event(side=1,atr=4.):return {'side':side,'quarter_end':30000,'entry_exec_ts':5000,'raw_entry_5s':100.,'signal_close':100.,'atr':atr}
def old(side=1):return {'status':'verified','variant':'normal_2r_20x','entry_ts':10000,'entry_raw':100.1 if side==1 else 99.9,'initial_stop':99. if side==1 else 101.}
def tape(side=1):return pd.DataFrame({'transact_time':[0,5000,6000,10000,12000,17000,30000,35000],
    'price':[100.,100.,100.,100.1 if side==1 else 99.9,102.2 if side==1 else 97.8,102.3 if side==1 else 97.7,100.,100.]})
def main():
    for side in (1,-1):
        e=event(side);o=old(side);data=tape(side);x=entry_1s.decide(e,o,data)
        assert x['status']=='verified' and x['entry_ts']==6000 and x['exit_signal_ts']==12000 and x['exit_ts']==17000 and x['reason']=='target'
        assert x['entry_ts']>=e['entry_exec_ts']+1000 and x['exit_ts']>=x['exit_signal_ts']+5000
        altered=data.copy();altered.loc[altered.transact_time>17000,'price']=50.
        assert entry_1s.decide(e,o,altered)==x
        bad=entry_1s.decide(event(side,atr=.1),o,data)
        assert bad['status']=='verified' and bad['reason']=='filled_beyond_risk_budget' and bad['entry_ts']==bad['exit_signal_ts']==6000 and bad['exit_ts']>=11000
        wrong=data.copy();wrong.loc[wrong.transact_time==5000,'price']=101.
        assert entry_1s.decide(e,o,wrong)['status']=='reference_disagreement'
    data=tape();extra=pd.DataFrame({'transact_time':[12000],'price':[98.]});tied=pd.concat([data,extra],ignore_index=True).sort_values('transact_time',kind='mergesort')
    assert entry_1s.decide(event(),old(),tied)['reason']=='stop'
    z={'all_checks_pass':True,'code_sha256':hashlib.sha256((H/'entry_1s.py').read_bytes()).hexdigest(),
       'checks':['long_short_entry_and_target','one_second_after_reference','five_second_exit_delay','future_perturbation',
                 'already_filled_risk_breach','source_reference_disagreement','same_timestamp_stop_priority']}
    (H/'一秒入场合成核验.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8');print('ENTRY51_SYNTHETIC_PASS',flush=True)
if __name__=='__main__':main()
