"""Test delayed exit, boundary, simultaneous signals, missing data and causality."""
import hashlib
import json
from pathlib import Path
from time_stop import apply

H=Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    base={'entry_ts':100000,'exit_signal_ts':160000,'entry_fill':100.,'actual_entry_risk':4.,'side':1}
    seq=[(129999,100.5),(130000,100.999),(134999,99.3),(135100,99.5)]
    x=apply(base,seq);assert x['action']=='early_exit' and x['exit_signal_ts']==130000 and x['exit_ts']==135100 and abs(x['exit_fill']-99.45025)<1e-10
    assert apply(base,[(130000,101.),(135000,101.)])['reason']=='progress_sufficient'
    assert apply({**base,'side':-1},[(130000,99.),(135000,99.)])['reason']=='progress_sufficient'
    assert apply({**base,'exit_signal_ts':130000},[(130000,99.),(135000,99.)])['reason']=='original_signal_first'
    assert apply({**base,'exit_signal_ts':131000},[(131000,99.),(136000,99.)])['reason']=='original_signal_first'
    assert apply(base,[(130000,99.)])['reason']=='missing_delayed_exit'
    assert apply(base,[(129999,99.)])['reason']=='missing_check_trade'
    y=apply(base,seq[:-1]+[(135100,103.)]);assert y['action']==x['action'] and y['exit_signal_ts']==x['exit_signal_ts'] and y['exit_raw']!=x['exit_raw']
    out={'all_checks_pass':True,'cases_checked':8,'code_sha256':sha(H/'time_stop.py'),'test_sha256':sha(Path(__file__)),
         'note':'One check, exact 0.25R boundary, signal priority and delayed execution; no profitability guarantee.'}
    (H/'进展退出合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT100_SYNTHETIC_PASS',8,flush=True)


if __name__=='__main__':main()
