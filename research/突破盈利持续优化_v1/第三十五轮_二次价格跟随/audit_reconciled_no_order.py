"""Independently verify the no-order subset and conservative win-count bounds."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
RAW=ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation'
def rejected(o,e,L):
    side=int(o['side']);ref=float(o['raw_entry_5s']);t=int(o['entry_exec_ts']);en=ref*(1+side*.0005)
    stop=float(o['stop_price']);atr=float(e['atr']);tr=float(o['signal_close']);dist=side*(en-stop);sigd=side*(tr-stop)
    return (((t//60000+480)%1440)>=1320 or t+5000>=e['quarter_end'] or side*(en-tr)>.25*atr or
            dist<=0 or dist>1.5*atr or 2*dist/en<.006 or 2*sigd/tr<.006 or dist/en+.003>=.5*(1/L-.01))
def main():
    result=json.loads((H/'严格复核不下单敏感性结果.json').read_text(encoding='utf-8'))
    sig=pd.read_parquet(H/'训练期分批'/'动态池逐笔信号筛查.parquet').set_index('observation_id')
    source=pd.read_parquet(P/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet').set_index('observation_id')
    diag=json.loads((H/'训练期分批'/'不完整数据下单位机会诊断.json').read_text(encoding='utf-8'))
    fingerprints={hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW.glob('*.json')}
    ids=set()
    for row in result['resolved_source_records']:
        obs=row['observation_id'];assert obs not in ids and sig.loc[obs,'status']=='upstream_data_unknown';ids.add(obs)
        assert row['checkpoint_sha256'] in fingerprints
        x=row['strict_reconciliation'];o=x['outcome'];assert x['reconciled'] and x['raw_matches_kline'] and x['aggregate_open_only'] and not x['paths_checked']
        for a,b in zip(x['aggregate_flow'],x['raw_flow']):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8)
        if o['status']=='flow_filter_not_met':
            buy,sell=x['aggregate_flow'];imb=o['side']*(buy-sell)/(buy+sell) if buy+sell else None
            if imb is not None:assert math.isclose(imb,o['five_imbalance'],rel_tol=1e-9,abs_tol=1e-10)
            assert o['five_count']<3 or imb is None or imb<.1 or o['side']*(o['raw_entry_5s']-o['level'])<=0
        elif o['status']=='known_risk_rejected':assert all(rejected(o,source.loc[obs],L) for L in (10,20))
        else:assert o['status'] in ('first_direction_ineligible','no_order_time')
    assert len(ids)==result['strict_no_order_reconciled']
    assert result['remaining_unknown']==result['training_initial_unknown']-len(ids)
    for row in result['rows']:
        d=next(x for x in diag['rows'] if x['period']=='2024_jan_apr' and x['variant']==row['variant'])
        assert d['verified_subset_events']==row['verified_events_unchanged'] and d['verified_subset_wins']==row['verified_wins_unchanged']
        assert math.isclose(row['optimistic_unit_win_rate_upper_pct'],100*(d['verified_subset_wins']+result['remaining_unknown'])/(d['verified_subset_events']+result['remaining_unknown']),rel_tol=1e-12)
    out={'strict_no_order_records_checked':len(ids),'remaining_unknown':result['remaining_unknown'],
         'four_unit_win_bounds_checked':len(result['rows']),'all_checks_pass':True,
         'note':'No raw archives were redownloaded in this sensitivity check; previously verified checkpoint hashes were matched.'}
    (H/'严格复核不下单敏感性独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FOLLOW35_NO_ORDER_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
