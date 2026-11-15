"""Independently reconstruct all labelled-pair statistics."""
import json
import math
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R100=P/'第一百轮_突破无进展提前退出'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def near(a,b):return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def main():
    bulk.runner.guard(start=True);report=json.loads((H/'大柱退出对照结果.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==bulk.sha(H/'summarize.py') and report['detail_sha256']==bulk.sha(H/'大柱对照逐笔.csv')
    label=pd.read_parquet(H/'事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    original=pd.read_parquet(R98/'原始逐笔批次/单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    paths=pd.read_parquet(R100/'进展退出单位账本.parquet').to_dict('records');detail=pd.read_csv(H/'大柱对照逐笔.csv').set_index(['observation_id','leverage']).to_dict('index')
    expected={}
    for r in paths:
        if r['risk_status']!='verified' or bool(r['liq_proxy']):continue
        obs=r['observation_id'];lev=int(r['variant'].rsplit('_',1)[1].rstrip('x')); lab=label[obs]
        group='unknown' if lab['status']!='verified' else 'large_aligned' if bool(lab['large_aligned']) else 'other'
        orig=original[(obs,r['variant'])];a=float(orig['net_per_unit_notional']);b=float(r['net_per_unit_notional']);saved=detail[(obs,lev)]
        assert saved['label']==group and saved['action']==r['time_stop_action']
        assert near(saved['original_net'],a) and near(saved['time_stop_net'],b) and near(saved['difference'],b-a)
        expected.setdefault((lev,group),[]).append((a,b,r['time_stop_action']))
    assert sum(map(len,expected.values()))==len(detail)
    for row in report['rows']:
        vals=expected.get((row['leverage'],row['label']),[]);n=len(vals);d=[b-a for a,b,_ in vals]
        assert row['trades']==n and row['early_exits']==sum(c=='early_exit' for _,_,c in vals)
        assert row['original_net_wins']==sum(a>0 for a,_,_ in vals) and row['time_stop_net_wins']==sum(b>0 for _,b,_ in vals)
        assert near(row['original_mean_pct_notional'],100*math.fsum(a for a,_,_ in vals)/n if n else None)
        assert near(row['time_stop_mean_pct_notional'],100*math.fsum(b for _,b,_ in vals)/n if n else None)
        assert row['better']==sum(x>1e-12 for x in d) and row['worse']==sum(x< -1e-12 for x in d) and row['unchanged']==sum(abs(x)<=1e-12 for x in d)
    out={'all_checks_pass':True,'paired_paths_checked':len(detail),'groups_checked':len(report['rows']),
         'result_sha256':bulk.sha(H/'大柱退出对照结果.json'),'detail_sha256':bulk.sha(H/'大柱对照逐笔.csv'),
         'code_sha256':bulk.sha(Path(__file__)),'note':'Trade outcomes grouped by verified completed-candle labels; not live signal or market-wide capture.'}
    (H/'大柱对照独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT102_SUMMARY_AUDIT',len(detail),flush=True)


if __name__=='__main__':main()
