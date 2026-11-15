"""Settle only risk-covered 2026 paths from previously verified public caches."""
import importlib.util,json,math,sys
from pathlib import Path
import pandas as pd
import run_observation as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def repair(x):
    v=x.get('repair');return (v.get('day'),v.get('sha256')) if isinstance(v,dict) else (None,None)
def main():
    runner.inputs('2026');OUT=H/'2026一秒观察分批';path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
    spec=importlib.util.spec_from_file_location('obs62cached',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    manifests=[P/'第四十六轮_固定十一加密币跨时段'/'2026'/'逐笔分批'/'动态池风险档案核验清单.json',
               P/'第四十七轮_一次重新突破确认'/'2026重试分批'/'动态池风险档案核验清单.json',
               P/'第五十一轮_缩短市价入场延迟'/'2026一秒入场分批'/'动态池风险档案核验清单.json']
    entries=[]
    for f in manifests:entries.extend(json.loads(f.read_text(encoding='utf-8')))
    local_path=H/'2026本地风险来源核验.json';local=json.loads(local_path.read_text(encoding='utf-8'))
    assert local['all_checks_pass'] and local['code_sha256']==runner.sha(H/'verify_local_risk.py')
    assert local['plan_sha256']==runner.sha(H/'本地风险补验方案.md')
    assert local['snapshot_sha256']==runner.sha(H/'2026中间批次_13候选'/'中间快照哈希.json')
    audit=json.loads((H/'2026本地风险独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['manifest_sha256']==runner.sha(local_path) and audit['audit_sha256']==runner.sha(H/'audit_local_risk.py')
    for x in local['archives']:
        assert runner.sha(Path(x['source_path']))==x['sha256'] and runner.sha(Path(x['cache_path']))==x['cache_sha256']
        entries.append(x)
    trusted={(x['kind'],x['contract'],x['month'],x['sha256'],*repair(x)) for x in entries if x['status']=='verified'}
    marks={};funds={};status={};used={};cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46'
    files=list(cache.glob('*.json'))+[Path(x['cache_path']) for x in local['archives']]
    for f in files:
        x=json.loads(f.read_text(encoding='utf-8'));key=(x['kind'],x['contract'],x['month']);full=(*key,x.get('sha256'),*repair(x))
        if x.get('status')!='verified' or full not in trusted:continue
        if key in used:assert used[key]['sha256']==x['sha256']
        else:used[key]={k:x[k] for k in ('kind','contract','month','status','sha256')}
        status[key]='verified'
        if x['kind']=='markPriceKlines':
            for bar in x['rows']:
                k=(x['contract'],int(bar['ts']))
                if k in marks:assert all(near(marks[k][n],bar[n]) for n in ('open','high','low','close'))
                else:marks[k]=bar
        else:
            if key in funds:assert funds[key]==x['rows']
            else:funds[key]=x['rows']
    funds={(symbol,month):v for (kind,symbol,month),v in funds.items()}
    signal=pd.read_parquet(OUT/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(OUT/'动态池延迟市价路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(signal[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    checked=[engine.settle(r,marks,funds,status) for r in valid.itertuples(index=False)]
    ledger=pd.concat([valid.reset_index(drop=True),pd.DataFrame(checked)],axis=1);ledger.to_parquet(OUT/'动态池单位收益与风险.parquet',index=False)
    q=json.loads((OUT/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));bad=bool(q['archive_errors'] or q['unexpected_event_count'] or q['unverified_path_count'])
    missing=int((~ledger.risk_status.eq('verified')).sum()) if len(ledger) else 0
    liq=int(ledger.liq_proxy.fillna(False).sum()) if 'liq_proxy' in ledger else 0
    info={'complete':not bad and missing==0 and liq==0,'tape_incomplete':bad,'verified_tape_paths':len(valid),'ledger_paths':len(ledger),
          'source_paths_sha256':runner.sha(OUT/'动态池延迟市价路径.parquet'),'risk_statuses':ledger.risk_status.value_counts().to_dict() if len(ledger) else {},
          'liquidation_proxy_paths':liq,'risk_cache_missing':missing,'local_archives_verified':len(local['archives']),
          'note':'Previously verified caches plus local ZIPs matched against official checksums; uncovered paths remain unknown.'}
    (OUT/'动态池单位筛查完整性.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'动态池风险档案核验清单.json').write_text(json.dumps(list(used.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_CACHED_RISK',json.dumps(info,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
