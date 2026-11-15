"""Check the independent scalar replay against explicit synthetic events."""
import hashlib,json
from pathlib import Path
from one_second_observation import decide
from test_one_second_observation import event,data
from audit_tape_samples import replay
H=Path(__file__).resolve().parent
def main():
    items=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(900,100.1),(1100,100.2),(2100,100.25),(5000,101.8),(10000,101.75)]
    for side in (1,-1):
        tape,bars=data(items,side);e=event(side);want=decide(e,tape,bars);assert replay(e,tape,bars,want)==2
        bad={**want,'decision_ts':want['decision_ts']+1}
        try:replay(e,tape,bars,bad)
        except AssertionError:pass
        else:raise AssertionError('independent_audit_failed_to_reject_wrong_timestamp')
    tie=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(900,100.1),(1100,100.2),(2100,100.25),(5000,101.8),(5000,99.5),(10000,100.)]
    tape,bars=data(tie);e=event(1);want=decide(e,tape,bars);assert replay(e,tape,bars,want)==2
    noorder=[(0,99.9),(100,100.1),(101,100.1),(200,100.1),(1100,100.2),(2100,100.25),(10000,100.)]
    tape,bars=data(noorder);e=event(1);want=decide(e,tape,bars);assert replay(e,tape,bars,want)==0
    out={'all_checks_pass':True,'long_short_and_tie':True,'no_order':True,'wrong_timestamp_rejected':True,
         'audit_code_sha256':hashlib.sha256((H/'audit_tape_samples.py').read_bytes()).hexdigest(),
         'decision_code_sha256':hashlib.sha256((H/'one_second_observation.py').read_bytes()).hexdigest()}
    (H/'独立重放合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_INDEPENDENT_SYNTHETIC_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
