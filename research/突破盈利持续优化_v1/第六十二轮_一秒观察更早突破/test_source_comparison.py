"""Prevent stale or misaligned original-path inputs from passing QA."""
import hashlib,json
from pathlib import Path
import pandas as pd
from run_observation import compare_baseline
H=Path(__file__).resolve().parent
def main():
    epoch=1700000000000
    actual={'status':'flow_filter_not_met','side':1,'decision_ts':epoch,'signal_close':100.,
            'entry_exec_ts':epoch+5001,'raw_entry_5s':100.1,'five_count':0,'buy_notional':0.,'sell_notional':0.,
            'five_imbalance':None,'stop_price':99.,'level':100.}
    reference=pd.Series(actual);empty=pd.DataFrame(columns=['observation_id','variant'])
    assert compare_baseline('x',actual,reference,empty)
    shifted=pd.Series({**actual,'decision_ts':epoch+1});assert not compare_baseline('x',actual,shifted,empty)
    broken=pd.Series({**actual,'five_imbalance':.2});assert not compare_baseline('x',actual,broken,empty)
    record={'all_checks_pass':True,'millisecond_mismatch_rejected':True,'matching_nulls_accepted':True,
        'missingness_disagreement_rejected':True,'runner_sha256':hashlib.sha256((H/'run_observation.py').read_bytes()).hexdigest(),
        'plan_sha256':hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()}
    (H/'原方案来源比较合成核验.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_COMPARISON_TEST_PASS',json.dumps(record,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
