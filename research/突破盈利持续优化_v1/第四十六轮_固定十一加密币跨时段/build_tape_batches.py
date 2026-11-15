"""Merge authorized prior tapes, new verified tapes and explicit unknowns."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
import stream_fixed11_tapes as stream
import verify_reuse_prefixes as reuse
H=Path(__file__).resolve().parent;I=H/'逐笔冻结输入';P=H.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for name,v in f['inputs'].items():assert sha(I/name)==v
    q=json.loads((H/'逐笔复用计划质量.json').read_text(encoding='utf-8'));assert sha(H/'逐笔复用计划.parquet')==q['plan_sha256']
    audit=json.loads((H/'新逐笔读取一致性核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass'] and audit['stream_fingerprint']==stream.FP
    plan=pd.read_parquet(H/'逐笔复用计划.parquet').set_index('observation_id')
    cand=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True)
    old=pd.concat([pd.read_parquet(I/'old_signal.parquet'),pd.read_parquet(I/'backup_signal.parquet')],ignore_index=True).set_index('observation_id')
    oldpaths=pd.concat([pd.read_parquet(I/'old_paths.parquet'),pd.read_parquet(I/'backup_paths.parquet')],ignore_index=True)
    assert cand.observation_id.is_unique and plan.index.is_unique and old.index.is_unique and not oldpaths.duplicated(['observation_id','variant']).any()
    prefix={}
    for file in reuse.WORK.glob('*.json'):
        z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified'
        ids=sorted(r['observation_id'] for r in z['rows']);key=hashlib.sha256((reuse.FP+'|'+z['contract']+'|'+z['day']+'|'+'|'.join(ids)).encode()).hexdigest()
        assert file.stem==key
        for r in z['rows']:
            assert r['observation_id'] not in prefix;prefix[r['observation_id']]={**r,'daily_sha256':z['daily_sha256']}
    new={};want=set(plan.index[plan.reuse_status.eq('need_new_tape')]);d=cand[cand.observation_id.isin(want)]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));file=stream.WORK/(stream.key_for(spec)+'.json')
        if not file.exists():continue
        z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified'
        for r in z['rows']:
            assert r['observation_id'] in want and r['observation_id'] not in new;new[r['observation_id']]={**r,'_source_archives':z['archives']}
    rows={};prov=[];fields=['side','decision_ts','signal_close','entry_exec_ts','raw_entry_5s','five_count','buy_notional','sell_notional','five_imbalance','stop_price','level']
    for e in cand.to_dict('records'):
        obs=e['observation_id'];p=plan.loc[obs];kind=p.reuse_status
        if kind=='prior_source_unknown':
            rows[obs]={'observation_id':obs,'status':'prior_source_disagreement'};prov.append({'observation_id':obs,'source':kind,'reason':p.reason});continue
        if kind=='need_new_tape':
            z=new.get(obs)
            if z is None:rows[obs]={'observation_id':obs,'status':'archive_pending'};prov.append({'observation_id':obs,'source':'pending_new_archive'});continue
            row={k:v for k,v in z.items() if k!='_source_archives'};rows[obs]=row
            prov.append({'observation_id':obs,'source':'new_tape','archives':z['_source_archives']});continue
        assert kind=='reuse_after_prefix_check';check=prefix.get(obs)
        if check is None or check['status']!='verified':
            rows[obs]={'observation_id':obs,'status':'reuse_prefix_unknown'}
            prov.append({'observation_id':obs,'source':'reuse_unknown','reason':None if check is None else check['status']});continue
        r=old.loc[obs];side=int(r['side'])
        if p.reason=='new_first_direction_ineligible':row={'observation_id':obs,'status':'first_direction_ineligible','side':side}
        else:
            row={'observation_id':obs,'status':r['status']}
            for key in fields:
                value=r.get(key)
                if not pd.isna(value):row[key]=value.item() if hasattr(value,'item') else value
            if r['status'] in ('qualified','known_risk_rejected'):
                row['prechecks']={str(lev):r[f'precheck_{lev}x'] for lev in (10,20) if not pd.isna(r[f'precheck_{lev}x'])}
                g=oldpaths[oldpaths.observation_id.eq(obs)];path={}
                for x in g.to_dict('records'):
                    variant=x.pop('variant');x.pop('observation_id');path[variant]={k:v for k,v in x.items() if not pd.isna(v)}
                row['paths']=path
            name='long' if side==1 else 'short';spec=json.loads(e[name+'_spec'])
            if spec is not None:
                for key in ('score','rvol','rank','liquidity_rank'):row[key]=spec[key]
        rows[obs]=row;prov.append({'observation_id':obs,'source':'reused_tape','old_checkpoint':check['old_checkpoint'],'daily_sha256':check['daily_sha256']})
    assert set(rows)==set(cand.observation_id)
    allmeta=[]
    for year in ('2024','2026'):
        sub=cand[cand.source_year.eq(year)];dest=H/year/'逐笔分批';dest.mkdir(exist_ok=True)
        signal=[];paths=[]
        for obs in sub.observation_id:
            row=rows[obs];pre=row.get('prechecks',{})
            for variant,v in row.get('paths',{}).items():paths.append({'observation_id':obs,'variant':variant,**v})
            signal.append({**{k:v for k,v in row.items() if k not in ('paths','prechecks')},'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
        s=pd.DataFrame(signal).merge(sub,on='observation_id',validate='one_to_one',suffixes=('','_candidate'))
        d=pd.DataFrame(paths)
        if len(d):assert not d.duplicated(['observation_id','variant']).any()
        s.to_parquet(dest/'动态池逐笔信号筛查.parquet',index=False);d.to_parquet(dest/'动态池延迟市价路径.parquet',index=False)
        benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
        missing=sorted(s.loc[s.status.eq('archive_pending'),'observation_id'])
        meta={'candidate_events':len(s),'event_statuses':s.status.value_counts().to_dict(),
              'unexpected_event_count':int((~s.status.isin(benign)).sum()),'variant_paths':len(d),
              'unverified_path_count':int((~d.status.eq('verified')).sum()) if len(d) else 0,
              'archive_errors':[{'status':'archive_pending','events':missing}] if missing else [],
              'note':'Unknown, unresolved and pending opportunities remain explicit; fixed 11 is survivorship-biased.'}
        (dest/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copyfile(I/'old_execution_plan.json',dest/'逐笔执行冻结方案.json')
        allmeta.append({'year':year,**meta})
    (H/'逐笔来源追踪.json').write_text(json.dumps(prov,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_TAPE_BATCHES',json.dumps(allmeta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
