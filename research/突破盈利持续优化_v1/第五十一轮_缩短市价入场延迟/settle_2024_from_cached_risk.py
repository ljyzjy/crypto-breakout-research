"""Reuse audited mark/funding rows; unknown 1s coverage stays unknown."""
import hashlib,importlib.util,json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'2024冻结输入';OUT=H/'2024一秒入场分批'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def repair_key(x):
    z=x.get('repair');return (z.get('day'),z.get('sha256')) if isinstance(z,dict) else (None,None)
def main():
    f=json.loads((H/'2024输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    test=json.loads((H/'一秒入场合成核验.json').read_text(encoding='utf-8'));assert test['all_checks_pass'] and test['code_sha256']==sha(H/'entry_1s.py')
    snap=H/'2024中间批次_31候选';z=json.loads((snap/'中间快照哈希.json').read_text(encoding='utf-8'));assert z['all_checks_pass']
    for n,v in z['files'].items():assert sha(snap/n)==v
    audit=P/'第四十六轮_固定十一加密币跨时段'/'固定十一币净账本独立核验.json'
    assert json.loads(audit.read_text(encoding='utf-8'))['all_checks_pass']
    assert (I/'retry_ledger.parquet').exists()
    assert json.loads((P/'第四十七轮_一次重新突破确认'/'单次重试净账本独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
    spec=importlib.util.spec_from_file_location('entry51_cache_engine',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
    snapshots={n:sha(OUT/n) for n in names};(OUT/'风险输入哈希.json').write_text(json.dumps(snapshots,ensure_ascii=False,indent=2),encoding='utf-8')
    files=[P/'第四十六轮_固定十一加密币跨时段'/'2024'/'逐笔分批'/'动态池风险档案核验清单.json',
           P/'第四十七轮_一次重新突破确认'/'2024重试分批'/'动态池风险档案核验清单.json',snap/'动态池风险档案核验清单.json']
    manifests=[]
    for p in files:manifests.extend(json.loads(p.read_text(encoding='utf-8')))
    trusted={(x['kind'],x['contract'],x['month'],x['sha256'],*repair_key(x)) for x in manifests if x['status']=='verified'}
    marks={};funds={};statuses={};used={};cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46'
    for file in cache.glob('*.json'):
        x=json.loads(file.read_text(encoding='utf-8'));key=(x['kind'],x['contract'],x['month']);full=(*key,x.get('sha256'),*repair_key(x))
        if x.get('status')!='verified' or full not in trusted:continue
        if key in used:assert used[key]['sha256']==x['sha256']
        else:used[key]={k:x[k] for k in ('kind','contract','month','status','sha256')}
        statuses[key]='verified'
        if x['kind']=='markPriceKlines':
            for bar in x['rows']:
                mk=(x['contract'],int(bar['ts']))
                if mk in marks:assert all(near(marks[mk][k],bar[k]) for k in ('open','high','low','close'))
                else:marks[mk]=bar
        else:
            if key in funds:assert funds[key]==x['rows']
            else:funds[key]=x['rows']
    funds={(sym,month):v for (kind,sym,month),v in funds.items()}
    signal=pd.read_parquet(OUT/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(OUT/'动态池延迟市价路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(signal[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    original=pd.concat([pd.read_parquet(I/'baseline_ledger.parquet'),pd.read_parquet(I/'retry_ledger.parquet')],ignore_index=True)
    orig={(r.observation_id,r.variant):r for r in original.itertuples(index=False)};assert len(orig)==len(original)
    checks=[];baseline_count=0
    for r in valid.itertuples(index=False):
        old=orig.get((r.observation_id,r.variant.replace('one_second_2r_','normal_2r_')))
        if old is None or old.risk_status!='verified' or bool(old.liq_proxy):checks.append({'risk_status':'baseline_risk_unknown'});continue
        try:
            rebuilt=engine.settle(old,marks,funds,statuses)
            if rebuilt['risk_status']!='verified' or bool(rebuilt['liq_proxy'])!=bool(old.liq_proxy) or not all(
                near(rebuilt[k],getattr(old,k)) for k in ('funding','entry_fee','exit_fee','net_per_unit_notional')):
                checks.append({'risk_status':'baseline_cache_disagreement'});continue
            baseline_count+=1;checks.append(engine.settle(r,marks,funds,statuses))
        except (KeyError,ValueError,TypeError):checks.append({'risk_status':'cached_risk_missing'})
    ledger=pd.concat([valid.reset_index(drop=True),pd.DataFrame(checks)],axis=1);ledger.to_parquet(OUT/'动态池单位收益与风险.parquet',index=False)
    meta=json.loads((OUT/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));bad=bool(meta['archive_errors'] or meta['unexpected_event_count'] or meta['unverified_path_count'])
    missing=int((~ledger.risk_status.eq('verified')).sum());liqs=int(ledger.liq_proxy.fillna(False).sum()) if 'liq_proxy' in ledger else 0
    quality={'complete':not bad and missing==0 and liqs==0,'tape_incomplete':bad,'verified_tape_paths':len(valid),'ledger_paths':len(ledger),
             'source_paths_sha256':sha(OUT/'动态池延迟市价路径.parquet'),'risk_statuses':ledger.risk_status.value_counts().to_dict(),
             'liquidation_proxy_paths':liqs,'archive_statuses':{'verified':len(used)},'archive_failures':[],
             'baseline_ledgers_reproduced':baseline_count,'missing_one_second_risk_paths':missing,
             'note':'Audited cached risk rows reused; 5s paths must reproduce, and uncovered 1s minutes remain unknown.'}
    (OUT/'动态池单位筛查完整性.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'动态池风险档案核验清单.json').write_text(json.dumps(list(used.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    for n,v in snapshots.items():assert sha(OUT/n)==v
    print('ENTRY51_2024_CACHED_RISK',json.dumps(quality,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
