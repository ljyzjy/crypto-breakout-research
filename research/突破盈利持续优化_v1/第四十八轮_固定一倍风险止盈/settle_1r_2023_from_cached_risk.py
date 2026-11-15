"""Reuse audited 2023 minute-risk caches after reproducing every 2R ledger."""
import hashlib,json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'2023冻结输入';OUT=H/'2023一倍止盈分批'
OLD=P/'第四十三轮_旧十一币2023年复核';RETRY=P/'第四十七轮_一次重新突破确认'/'2023重试分批'
sys.path.insert(0,str(OLD));import settle_2023_serial_engine as engine
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def repair_key(x):
    z=x.get('repair');return (z.get('day'),z.get('sha256')) if isinstance(z,dict) else (None,None)
def main():
    f=json.loads((H/'2023输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    assert json.loads((I/'retry_audit.json').read_text(encoding='utf-8'))['all_checks_pass']
    oldaudit=json.loads((OLD/'部分批次'/'2023净账本独立核验.json').read_text(encoding='utf-8'))
    assert oldaudit['independently_checked_verified_paths']>=168 and oldaudit['unknown_win_count_bounds_rechecked']
    names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
    snapshots={n:sha(OUT/n) for n in names};(OUT/'风险输入哈希.json').write_text(json.dumps(snapshots,ensure_ascii=False,indent=2),encoding='utf-8')
    manifests=[]
    for p in (OLD/'部分批次'/'动态池风险档案核验清单.json',RETRY/'动态池风险档案核验清单.json'):
        manifests.extend(json.loads(p.read_text(encoding='utf-8')))
    trusted={(x['kind'],x['contract'],x['month'],x['sha256'],*repair_key(x)) for x in manifests if x['status']=='verified'}
    marks={};funds={};statuses={};used={};cache=ROOT/'work'/'point_in_time_universe33'/'risk_old11_2023_serialv1'
    for file in cache.glob('*.json'):
        z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month']);full=(*key,z.get('sha256'),*repair_key(z))
        if z.get('status')!='verified' or full not in trusted:continue
        if key in used:assert used[key]['sha256']==z['sha256']
        else:used[key]={k:z[k] for k in ('kind','contract','month','status','sha256')}
        statuses[key]='verified'
        if z['kind']=='markPriceKlines':
            for x in z['rows']:
                mk=(z['contract'],int(x['ts']))
                if mk in marks:
                    assert all(near(marks[mk][k],x[k]) for k in ('open','high','low','close'))
                else:marks[mk]=x
        else:
            if key in funds:
                assert len(funds[key])==len(z['rows'])
                assert all(a==b for a,b in zip(funds[key],z['rows']))
            else:funds[key]=z['rows']
    funds={(sym,month):v for (kind,sym,month),v in funds.items()}
    signal=pd.read_parquet(OUT/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(OUT/'动态池延迟市价路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(signal[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    original=pd.concat([pd.read_parquet(I/'baseline_ledger.parquet'),pd.read_parquet(I/'retry_ledger.parquet')],ignore_index=True)
    orig={(r.observation_id,r.variant):r for r in original.itertuples(index=False)};assert len(orig)==len(original)
    checks=[];baseline_count=0;unknown=[]
    for r in valid.itertuples(index=False):
        old=orig.get((r.observation_id,r.variant.replace('_1r_','_2r_')))
        if old is None or old.risk_status!='verified' or bool(old.liq_proxy):
            checks.append({'risk_status':'baseline_risk_unknown'});unknown.append(r.observation_id);continue
        try:
            old_rebuilt=engine.settle(old,marks,funds,statuses)
            if old_rebuilt['risk_status']!='verified' or bool(old_rebuilt['liq_proxy'])!=bool(old.liq_proxy) or not all(
                near(old_rebuilt[k],getattr(old,k)) for k in ('funding','entry_fee','exit_fee','net_per_unit_notional')):
                checks.append({'risk_status':'baseline_cache_disagreement'});unknown.append(r.observation_id);continue
            baseline_count+=1;checks.append(engine.settle(r,marks,funds,statuses))
        except (KeyError,ValueError,TypeError) as exc:
            checks.append({'risk_status':'cached_risk_missing'});unknown.append(r.observation_id)
    ledger=pd.concat([valid.reset_index(drop=True),pd.DataFrame(checks)],axis=1)
    ledger.to_parquet(OUT/'动态池单位收益与风险.parquet',index=False)
    meta=json.loads((OUT/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));bad=bool(meta['archive_errors'] or meta['unexpected_event_count'] or meta['unverified_path_count'])
    missing=int((~ledger.risk_status.eq('verified')).sum());liqs=int(ledger.liq_proxy.fillna(False).sum()) if 'liq_proxy' in ledger else 0
    quality={'complete':not bad and missing==0 and liqs==0,'tape_incomplete':bad,'verified_tape_paths':len(valid),'ledger_paths':len(ledger),
             'source_paths_sha256':sha(OUT/'动态池延迟市价路径.parquet'),'risk_statuses':ledger.risk_status.value_counts().to_dict(),
             'liquidation_proxy_paths':liqs,'archive_statuses':{'verified':len(used)},'archive_failures':[],
             'baseline_ledgers_reproduced':baseline_count,'unknown_cache_paths':len(unknown),
             'note':'Audited cached official risk rows reused; each old 2R path must independently reproduce before 1R is settled.'}
    (OUT/'动态池单位筛查完整性.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'动态池风险档案核验清单.json').write_text(json.dumps(list(used.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    for n,v in snapshots.items():assert sha(OUT/n)==v
    print('EXIT1R48_CACHED_RISK',json.dumps(quality,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
