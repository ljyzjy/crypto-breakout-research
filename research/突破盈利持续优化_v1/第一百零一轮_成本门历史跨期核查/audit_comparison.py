"""Independently rebuild all cost-gate rows from frozen signal and risk ledgers."""
import json
import math
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import sys
import pandas as pd
import pyarrow.parquet as pq

H=Path(__file__).resolve().parent;P=H.parent;R95=P/'第九十五轮_扩充训练滚动预测';D=Decimal
sys.path.insert(0,str(R95));import run_expanded_walkforward as prior


def near(a,b):return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def source(period):
    if period=='2026_aug_oct':
        root=prior.R81/'冻结结果';manifest=json.loads((root/'冻结哈希.json').read_text(encoding='utf-8'))
    else:
        root=(P/'第七十三轮_二零二三扩展核验/2023基础冻结结果' if period=='2023' else P/f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
        f77=json.loads((prior.R77/'冻结时点.json').read_text(encoding='utf-8'));manifest_path=root/'完整快照哈希.json'
        assert prior.sha(manifest_path)==f77['base_snapshots'][period];manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    files=['batch/动态池逐笔信号筛查.parquet','batch/动态池单位收益与风险.parquet']
    for f in files:assert prior.sha(root/f)==manifest['files'][f]
    sig={r['observation_id']:r for r in pq.read_table(root/files[0]).to_pylist()}
    rows=[r for r in pq.read_table(root/files[1]).to_pylist() if r['status']==r['risk_status']=='verified' and r['liq_proxy'] is False]
    return sig,rows


def stats(rows,unknown):
    vals=[float(r['net_per_unit_notional']) for r in rows];wins=[v for v in vals if v>0];losses=[v for v in vals if v<0]
    return {'known_trades':len(vals),'net_wins':len(wins),'net_win_rate_pct':100*len(wins)/len(vals) if vals else None,
            'mean_net_pct_notional':100*math.fsum(vals)/len(vals) if vals else None,
            'profit_factor':math.fsum(wins)/-math.fsum(losses) if losses else None,
            'active_utc_days':len({datetime.fromtimestamp(int(r['entry_ts'])/1000,timezone.utc).date() for r in rows}),
            'unknown_candidates':unknown}


def main():
    prior.guard.guard(start=True);report=json.loads((H/'成本门跨期结果.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==prior.sha(H/'run_comparison.py') and report['detail_sha256']==prior.sha(H/'成本门逐笔明细.csv')
    prior_audit=json.loads((R95/'扩充滚动模型独立核验.json').read_text(encoding='utf-8'));assert prior_audit['all_checks_pass']
    prior_result=json.loads((R95/'扩充训练滚动结果.json').read_text(encoding='utf-8'))['rows']
    details=pd.read_csv(H/'成本门逐笔明细.csv',dtype=str,keep_default_na=False);checked=0
    for period in ('2023','2024','2026','2026_aug_oct'):
        signals,ledger=source(period)
        for lev in (10,20):
            variant=f'one_observation_2r_{lev}x';orig=[r for r in ledger if r['variant']==variant];selected=[]
            d=details[(details.period==period)&(details.leverage==str(lev))].set_index('observation_id').to_dict('index')
            assert len(orig)==len(d) and len({r['observation_id'] for r in orig})==len(orig)
            for r in orig:
                obs=r['observation_id'];s=signals[obs];x=d[obs];side=int(s['side']);p=D(str(s['raw_entry_1s']));stop=D(str(s['stop_price']))
                dist=D(side)*(p-stop)/p;yes=dist>=D('.004')
                assert x['selected']==str(yes) and abs(D(x['fraction'])-dist)<D('1e-15')
                assert int(D(x['reference_ts']))>=int(D(x['decision_ts']))+1000 and int(D(x['entry_ts']))>=int(D(x['reference_ts']))+1000
                assert near(x['net'],r['net_per_unit_notional']) and near(x['reference'],p) and near(x['stop'],stop)
                if yes:selected.append(r)
                checked+=1
            row=next(x for x in report['rows'] if x['period']==period and x['leverage']==lev)
            unknown=next(x for x in prior_result if x['test_period']==period and x['leverage']==lev)['baseline']['unknown_candidates']
            for key,records in [('baseline',orig),('cost_gate',selected)]:
                expected=stats(records,unknown)
                assert all(near(row[key][k],v) for k,v in expected.items()),(period,lev,key)
            assert row['rejected_known_trades']==len(orig)-len(selected)
    out={'all_checks_pass':True,'known_paths_checked':checked,'summary_groups_checked':len(report['rows']),
         'result_sha256':prior.sha(H/'成本门跨期结果.json'),'detail_sha256':prior.sha(H/'成本门逐笔明细.csv'),
         'code_sha256':prior.sha(Path(__file__)),'note':'Independent frozen-Parquet gate and arithmetic; unknown source paths and non-blind sampling persist.'}
    (H/'成本门跨期独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT101_AUDIT_PASS',checked,flush=True)


if __name__=='__main__':main()
