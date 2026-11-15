"""Construct fixed dual-gated risk batches without excluding unknown candidates."""
import hashlib, json, shutil
from pathlib import Path
import pandas as pd

H=Path(__file__).resolve().parent; I=H/'冻结输入'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md') == f['plan_sha256']
    for name,value in f['inputs'].items(): assert sha(I/name)==value
    assert json.loads((H/'事前市场过滤时序核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    q=json.loads((H/'事前市场过滤质量.json').read_text(encoding='utf-8'))
    assert sha(H/'候选事前市场过滤.parquet')==q['decision_sha256']
    signal=pd.read_parquet(I/'baseline_signal.parquet')
    paths=pd.read_parquet(I/'baseline_paths.parquet')
    decisions=pd.read_parquet(H/'候选事前市场过滤.parquet')
    s=signal.merge(decisions,on=['observation_id','quarter_start'],validate='one_to_one')
    assert len(s)==len(signal)
    summaries=[]
    for period in ('2024_may_jun','2026_may_jul'):
        dest=H/period;dest.mkdir(exist_ok=True)
        x=s[s.research_period.eq(period)].copy()
        eligible={}
        for r in x.to_dict('records'):
            if r['market_status']!='allowed' or r['status']!='qualified' or int(r['side'])!=int(r['allowed_side']):continue
            for lev in (10,20):
                if r.get(f'precheck_{lev}x')=='passed': eligible[(r['observation_id'],f'normal_2r_{lev}x')]=True
        p=paths[[bool(eligible.get((a,b))) for a,b in zip(paths.observation_id,paths.variant)]].copy()
        assert not p.duplicated(['observation_id','variant']).any()
        # Keep original full candidate universe for transparent no-order/unknown accounting.
        raw=x[signal.columns].copy();raw.to_parquet(dest/'动态池逐笔信号筛查.parquet',index=False)
        p.to_parquet(dest/'动态池延迟市价路径.parquet',index=False)
        benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
        meta={'candidate_events':len(raw),'event_statuses':raw.status.value_counts().to_dict(),
              'unexpected_event_count':int((~raw.status.isin(benign)).sum()),'variant_paths':len(p),
              'unverified_path_count':int((~p.status.eq('verified')).sum()) if len(p) else 0,
              'archive_errors':[],
              'note':'All source discrepancies are retained; ledger restricted to prior-gated normal-2R opportunities.'}
        (dest/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copyfile(I/'original_plan.json',dest/'逐笔执行冻结方案.json')
        hashes={name:sha(dest/name) for name in ['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']}
        hashes['decision_sha256']=q['decision_sha256'];hashes['research_plan_sha256']=f['plan_sha256']
        (dest/'风险批次冻结哈希.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
        summaries.append({'period':period,'candidates':len(raw),'selected_path_records':len(p),
                          'source_discrepancies':meta['unexpected_event_count']})
    print('CROSS44_RISK_BATCHES',json.dumps(summaries,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
