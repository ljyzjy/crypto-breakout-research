"""Perturb old exits and verify the new P10 candidate set is unchanged."""
import json,shutil
from pathlib import Path
import numpy as np,pandas as pd
import prepare_follow_candidates as module
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
work=ROOT/'work'/'follow35_lookahead_test';work.mkdir(parents=True,exist_ok=True)
shutil.copyfile(HERE/'冻结研究方案.json',work/'冻结研究方案.json')
expected=pd.read_parquet(HERE/'二次跟随事前候选.parquet').sort_values('observation_id').reset_index(drop=True)
reader=pd.read_parquet;original_here=module.HERE
def perturbed(path,*args,**kwargs):
    d=reader(path,*args,**kwargs)
    if Path(path).name=='动态池延迟市价路径.parquet':
        for k in ('exit_ts','exit_raw','exit_fill','exit_signal_ts'):
            if k in d:d[k]=123456789
        d['reason']='future_perturbed';d['status']='future_status_perturbed'
    return d
try:
    module.HERE=work;module.pd.read_parquet=perturbed;module.main()
finally:
    module.pd.read_parquet=reader;module.HERE=original_here
got=reader(work/'二次跟随事前候选.parquet').sort_values('observation_id').reset_index(drop=True)
pd.testing.assert_frame_equal(expected,got,check_dtype=True)
out={'all_candidates_checked':len(expected),'old_exit_prices_times_reasons_and_status_perturbed':True,
     'candidate_set_and_fields_unchanged':True,'p10_is_signal_not_fill':True}
(HERE/'二次跟随未来扰动核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('FOLLOW35_NO_LOOKAHEAD_TEST',json.dumps(out),flush=True)
