"""Compute the stricter P5 risk buffer without reading any future path."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def buffer_ratio(e):
    side=int(e['side']);atr=float(e['atr']);ref=float(e['raw_entry_5s']);cross=float(e['signal_close'])
    if side not in (-1,1) or atr<=0 or ref<=0 or cross<=0:raise ValueError('bad_preentry_features')
    if int(e['entry_exec_ts'])<int(e['decision_ts'])+5000 or int(e['entry_exec_ts'])>=int(e['quarter_end']):raise ValueError('bad_preentry_time')
    value=side*(ref*(1+side*.0005)-cross)/atr
    if not np.isfinite(value):raise ValueError('nonfinite')
    return value
def decisions(sig,market):
    d=sig.merge(market,on=['observation_id','quarter_start'],validate='one_to_one');rows=[]
    for e in d.to_dict('records'):
        for lev in (10,20):
            status=e['status'];ms=e['market_status'];side=int(e['allowed_side']);ratio=None
            if ms=='known_no_order':decision='known_no_order'
            elif status not in BENIGN:
                possible=ms=='market_unknown' or (side==1 and e['long_known_eligible']) or (side==-1 and e['short_known_eligible'])
                decision='source_unknown' if possible else 'known_no_order'
            elif status!='qualified':decision='known_no_order'
            elif pd.isna(e.get(f'precheck_{lev}x')):decision='precheck_unknown'
            elif e[f'precheck_{lev}x']!='passed':decision='known_no_order'
            else:
                try:
                    ratio=buffer_ratio(e)
                    if ratio>.125:decision='buffer_rejected'
                    elif ms=='market_unknown':decision='market_unknown'
                    elif int(e['side'])!=side:decision='known_no_order'
                    else:decision='selected_known_inputs'
                except (ValueError,TypeError,KeyError,OverflowError):decision='feature_unknown'
            rows.append({'observation_id':e['observation_id'],'leverage':lev,'decision':decision,'buffer_ratio_at_p5':ratio})
    out=pd.DataFrame(rows);assert not out.duplicated(['observation_id','leverage']).any()
    return out.sort_values(['observation_id','leverage']).reset_index(drop=True)
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==f['plan_sha256']
    for n,v in f['files'].items():assert hashlib.sha256((I/n).read_bytes()).hexdigest()==v
    sig=pd.read_parquet(I/'signal.parquet');market=pd.read_parquet(I/'market_decisions.parquet')
    score=decisions(sig,market);score.to_parquet(H/'P5缓冲事前决定.parquet',index=False)
    x={'counts':score.groupby(['leverage','decision']).size().reset_index(name='count').to_dict('records'),
       'decision_sha256':hashlib.sha256((H/'P5缓冲事前决定.parquet').read_bytes()).hexdigest(),
       'note':'Only P5 known prices/ATR, prior dual-market decision and original prechecks used. No ledger was read.'}
    (H/'缓冲事前决定质量.json').write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BUFFER41_CAUSAL_DECISIONS',json.dumps(x,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
