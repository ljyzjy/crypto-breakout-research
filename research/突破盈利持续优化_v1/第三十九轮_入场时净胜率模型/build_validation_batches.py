"""Freeze same-period original paths only after the model decisions were locked."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;I=H/'冻结输入';ORIG=P/'第三十三轮_动态池逐笔执行'
def main():
    snap=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    scoremeta=json.loads((H/'事前预测质量.json').read_text(encoding='utf-8'))
    audit=json.loads((H/'模型独立及时序核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['predictions_unchanged']
    assert hashlib.sha256((H/'事前固定预测.parquet').read_bytes()).hexdigest()==scoremeta['score_sha256']
    for name,item in snap['inputs'].items():assert hashlib.sha256((I/name).read_bytes()).hexdigest()==item['sha256']
    sig=pd.read_parquet(I/'all_signal.parquet');paths=pd.read_parquet(I/'all_paths.parquet');scores=pd.read_parquet(H/'事前固定预测.parquet')
    meta=json.loads((I/'all_quality.json').read_text(encoding='utf-8'))
    assert not meta['archive_errors'] and not sig.observation_id.duplicated().any() and not paths.duplicated(['observation_id','variant']).any()
    original_plan=ORIG/'逐笔执行冻结方案.json';assert hashlib.sha256(original_plan.read_bytes()).hexdigest()==meta['plan_sha256']
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    for period,folder in [('2024_may_jun','2024后续比较批次'),('2026_may_jul','2026后续比较批次')]:
        q=scores[scores.period.eq(period)];ids=set(q.observation_id);s=sig[sig.observation_id.isin(ids)].copy();p=paths[paths.observation_id.isin(ids)].copy()
        assert len(s)==len(ids) and len(q)==2*len(ids)
        out=H/folder;out.mkdir(exist_ok=True)
        s.to_parquet(out/'动态池逐笔信号筛查.parquet',index=False);p.to_parquet(out/'动态池延迟市价路径.parquet',index=False)
        quality={'candidate_events':len(s),'event_statuses':s.status.value_counts().to_dict(),
                 'unexpected_event_count':int((~s.status.isin(benign)).sum()),'variant_paths':len(p),
                 'unverified_path_count':int((~p.status.eq('verified')).sum()) if len(p) else 0,'archive_errors':[],
                 'model_decision_sha256':scoremeta['score_sha256'],
                 'note':'All original paths included as baseline; model decisions were frozen before this batch was built.'}
        (out/'动态池逐笔提取质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copyfile(original_plan,out/'逐笔执行冻结方案.json')
        shutil.copyfile(ORIG/'不完整数据敏感性规则.json',out/'不完整数据敏感性规则.json')
        print('NETMODEL39_VALIDATION_BATCH',period,json.dumps(quality,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
