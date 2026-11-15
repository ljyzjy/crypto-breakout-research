"""Check P5 buffer threshold and invariance to synthetic future values."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from prepare_buffer_decisions import decisions,buffer_ratio
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def main():
    e={'side':1,'atr':8.,'raw_entry_5s':2000.,'signal_close':2000.,'entry_exec_ts':6000,'decision_ts':1000,'quarter_end':60000}
    value=buffer_ratio(e);assert np.isclose(value,.125,rtol=0,atol=1e-12) and value<=.125
    e['signal_close']=1999.99;assert buffer_ratio(e)>.125
    s=pd.read_parquet(I/'signal.parquet');market=pd.read_parquet(I/'market_decisions.parquet');before=decisions(s,market)
    future=s.copy();future['entry_fill']=10**12;future['exit_ts']=9_999_999_999_999;future['exit_fill']=10**12
    future['net_per_unit_notional']=-999.;future['exit_reason']='altered_future'
    after=decisions(future,market);pd.testing.assert_frame_equal(before,after,check_dtype=True)
    saved=pd.read_parquet(H/'P5缓冲事前决定.parquet');pd.testing.assert_frame_equal(before,saved,check_dtype=True)
    out={'threshold_equality_and_above_checked':True,'candidate_leverage_decisions_checked':len(before),
         'future_price_exit_and_pnl_perturbed':True,'decisions_unchanged':True,'all_checks_pass':True}
    (H/'缓冲时序独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BUFFER41_CAUSALITY_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
