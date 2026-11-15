"""Plan conservative reuse only when prior execution inputs match exactly."""
import hashlib,json
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'逐笔冻结输入'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,digest in f['inputs'].items():assert sha(I/n)==digest
    for item in f['code'].values():assert sha(Path(item['path']))==item['sha256']
    cand=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True)
    old=pd.concat([pd.read_parquet(I/'old_signal.parquet'),pd.read_parquet(I/'backup_signal.parquet')],ignore_index=True)
    assert cand.observation_id.is_unique and old.observation_id.is_unique
    byid={r['observation_id']:r for r in old.to_dict('records')};rows=[]
    for e in cand.to_dict('records'):
        obs=e['observation_id'];previous=byid.get(obs);status='need_new_tape';reason='new_candidate'
        if previous is not None:
            numeric=['upper','lower','atr'];exact=all(not pd.isna(previous.get(k)) and float(previous[k])==float(e[k]) for k in numeric)
            exact=exact and all(previous[k]==e[k] for k in ('symbol','contract','trigger_minute','quarter_start','quarter_end'))
            if not exact:reason='prior_execution_inputs_differ'
            elif previous['status'] not in {'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}:
                status='prior_source_unknown';reason=str(previous['status'])
            elif pd.isna(previous.get('side')):reason='first_side_missing'
            else:
                side=int(previous['side']);assert side in (1,-1)
                name='long' if side==1 else 'short'
                if not bool(e[name+'_known_eligible']):
                    status='reuse_after_prefix_check';reason='new_first_direction_ineligible'
                elif previous['status']=='first_direction_ineligible':reason='newly_eligible_direction'
                elif previous['status']=='no_order_time':
                    status='reuse_after_prefix_check';reason='same_no_order_time'
                else:
                    spec=json.loads(e[name+'_spec']);assert spec is not None
                    same=all(not pd.isna(previous.get(k)) and float(previous[k])==float(spec[k]) for k in ('stop_price','level'))
                    if same:status='reuse_after_prefix_check';reason='exact_execution_inputs'
                    else:reason='stop_or_level_differs'
        rows.append({'observation_id':obs,'source_year':e['source_year'],'contract':e['contract'],'day':e['day'],
                     'reuse_status':status,'reason':reason})
    result=pd.DataFrame(rows);assert result.observation_id.is_unique
    result.to_parquet(H/'逐笔复用计划.parquet',index=False)
    out={'candidate_events':len(result),'year_status_counts':{str(y):g.reuse_status.value_counts().to_dict() for y,g in result.groupby('source_year')},
         'status_counts':result.reuse_status.value_counts().to_dict(),'plan_sha256':sha(H/'逐笔复用计划.parquet'),
         'note':'Reuse still requires independently rechecking official daily 1m prefix; changed or unresolved inputs are never treated as known.'}
    (H/'逐笔复用计划质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_REUSE_PLAN',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
