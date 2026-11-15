"""Preserve the explicitly incomplete 13-group snapshot before further work."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;B=H/'2026一秒观察分批';OUT=H/'2026中间批次_13候选'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert not OUT.exists();progress=json.loads((H/'2026一秒观察逐笔进度.json').read_text(encoding='utf-8'))
    assert progress['processed_groups']==13 and progress['total_groups']==35
    q=json.loads((B/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));risk=json.loads((B/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
    assert q['event_statuses']['archive_pending']==22 and q['event_statuses']['prior_source_unknown']==4
    assert risk['tape_incomplete'] and risk['risk_cache_missing']==4 and risk['risk_statuses']['verified']==4
    comparison=json.loads((H/'2026一秒观察对照.json').read_text(encoding='utf-8'))
    assert all(r['one_second_observation']['trades']==2 and r['one_second_observation']['unknown']==28 for r in comparison['rows'])
    cps=sorted((ROOT/'work'/'oneobs62_2026'/'tape').glob('*.json'));assert len(cps)==13
    files=[B/'动态池逐笔信号筛查.parquet',B/'动态池延迟市价路径.parquet',B/'动态池逐笔提取质量.json',B/'逐笔执行冻结方案.json',
           B/'动态池单位收益与风险.parquet',B/'动态池单位筛查完整性.json',B/'动态池风险档案核验清单.json',
           H/'2026一秒观察对照.json',H/'2026一秒观察已核验机会.parquet',H/'2026一秒观察逐笔进度.json']
    OUT.mkdir()
    for f in files:shutil.copy2(f,OUT/f.name);assert sha(f)==sha(OUT/f.name)
    info={'all_checks_pass':True,'groups_processed':13,'groups_total':35,'original_source_unknown':4,'archive_pending':22,
          'additional_risk_unknown_events':2,'risk_verified_unit_opportunities_per_leverage':2,
          'files':{f.name:sha(OUT/f.name) for f in files},'checkpoint_sha256':{str(f):sha(f) for f in cps},
          'note':'Non-random size-ordered partial data; no public-tape sample audit yet and no performance conclusion.'}
    (OUT/'中间快照哈希.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_PARTIAL_FROZEN',json.dumps({k:v for k,v in info.items() if k not in ('files','checkpoint_sha256')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
