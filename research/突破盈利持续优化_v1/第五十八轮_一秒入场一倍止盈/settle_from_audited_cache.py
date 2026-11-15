"""Reproduce every old 1s/2R ledger before settling its shorter 1R path."""
import hashlib,importlib.util,json,math,sys
from pathlib import Path
import pandas as pd
import run_early_1r as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def repair(x):
    r=x.get('repair');return (r.get('day'),r.get('sha256')) if isinstance(r,dict) else (None,None)
def main(year):
    runner.sources(year);I=H/f'{year}冻结输入';OUT=H/f'{year}一秒一倍分批'
    path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
    spec=importlib.util.spec_from_file_location('risk58',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    manifests=json.loads((I/'risk_manifest.json').read_text(encoding='utf-8'))
    trusted={(x['kind'],x['contract'],x['month'],x['sha256'],*repair(x)) for x in manifests if x['status']=='verified'}
    marks={};funds={};status={};used={};cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46'
    for file in cache.glob('*.json'):
        x=json.loads(file.read_text(encoding='utf-8'));key=(x['kind'],x['contract'],x['month']);full=(*key,x.get('sha256'),*repair(x))
        if x.get('status')!='verified' or full not in trusted:continue
        if key in used:assert used[key]['sha256']==x['sha256']
        else:used[key]={k:x[k] for k in ('kind','contract','month','status','sha256')}
        status[key]='verified'
        if x['kind']=='markPriceKlines':
            for bar in x['rows']:
                mk=(x['contract'],int(bar['ts']))
                if mk in marks:assert all(near(marks[mk][k],bar[k]) for k in ('open','high','low','close'))
                else:marks[mk]=bar
        else:
            if key in funds:assert funds[key]==x['rows']
            else:funds[key]=x['rows']
    funds={(symbol,month):v for (kind,symbol,month),v in funds.items()}
    signal=pd.read_parquet(OUT/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(OUT/'动态池延迟市价路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(signal[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    original=pd.read_parquet(I/'ledger_2r.parquet');old={(r.observation_id,r.variant):r for r in original.itertuples(index=False)}
    assert len(old)==len(original);checks=[];reproduced=0
    for r in valid.itertuples(index=False):
        ref=old.get((r.observation_id,r.variant.replace('one_second_1r_','one_second_2r_')))
        if ref is None or ref.risk_status!='verified' or bool(ref.liq_proxy):checks.append({'risk_status':'baseline_risk_unknown'});continue
        if int(r.entry_ts)!=int(ref.entry_ts) or not near(r.entry_fill,ref.entry_fill) or int(r.exit_ts)>int(ref.exit_ts):
            checks.append({'risk_status':'paired_path_disagreement'});continue
        try:
            prior=engine.settle(ref,marks,funds,status)
            if prior['risk_status']!='verified' or bool(prior['liq_proxy'])!=bool(ref.liq_proxy) or not all(near(prior[k],getattr(ref,k)) for k in ('funding','entry_fee','exit_fee','net_per_unit_notional')):
                checks.append({'risk_status':'baseline_cache_disagreement'});continue
            reproduced+=1;checks.append(engine.settle(r,marks,funds,status))
        except (KeyError,ValueError,TypeError):checks.append({'risk_status':'cached_risk_missing'})
    ledger=pd.concat([valid.reset_index(drop=True),pd.DataFrame(checks)],axis=1);ledger.to_parquet(OUT/'动态池单位收益与风险.parquet',index=False)
    q=json.loads((OUT/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));bad=bool(q['archive_errors'] or q['unexpected_event_count'] or q['unverified_path_count'])
    missing=int((~ledger.risk_status.eq('verified')).sum()) if len(ledger) else 0
    liq=int(ledger.liq_proxy.fillna(False).sum()) if 'liq_proxy' in ledger else 0
    info={'complete':not bad and missing==0 and liq==0,'tape_incomplete':bad,'verified_tape_paths':len(valid),'ledger_paths':len(ledger),
          'source_paths_sha256':sha(OUT/'动态池延迟市价路径.parquet'),'risk_statuses':ledger.risk_status.value_counts().to_dict() if len(ledger) else {},
          'liquidation_proxy_paths':liq,'baseline_ledgers_reproduced':reproduced,'risk_cache_missing':missing,
          'note':'Old one-second 2R ledger reproduced first; unmatched or unavailable paths stay unknown.'}
    (OUT/'动态池单位筛查完整性.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'动态池风险档案核验清单.json').write_text(json.dumps(list(used.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY1R58_RISK',year,json.dumps(info,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
