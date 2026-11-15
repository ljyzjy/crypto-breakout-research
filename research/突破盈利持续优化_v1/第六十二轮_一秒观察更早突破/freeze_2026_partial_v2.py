"""Freeze the same 13 groups after the checksum-verified local risk repair."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;B=H/'2026一秒观察分批';OUT=H/'2026中间批次_13候选_补齐风险'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert not OUT.exists();old=json.loads((H/'2026中间批次_13候选'/'中间快照哈希.json').read_text(encoding='utf-8'))
    assert old['all_checks_pass'] and old['groups_processed']==13
    risk=json.loads((B/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
    arithmetic=json.loads((H/'2026中间批次风险算术核验.json').read_text(encoding='utf-8'))
    assert risk['tape_incomplete'] and risk['risk_statuses']=={'verified':8} and risk['risk_cache_missing']==0
    assert arithmetic['arithmetic_checks_pass'] and arithmetic['audited_risk_paths']==8 and not arithmetic['public_tape_sample_audit_complete']
    assert arithmetic['source_paths_sha256']==sha(B/'动态池延迟市价路径.parquet') and arithmetic['ledger_sha256']==sha(B/'动态池单位收益与风险.parquet')
    result=json.loads((H/'2026一秒观察对照.json').read_text(encoding='utf-8'))
    assert all(x['one_second_observation']['trades']==4 and x['one_second_observation']['unknown']==26 for x in result['rows'])
    files=[B/'动态池逐笔信号筛查.parquet',B/'动态池延迟市价路径.parquet',B/'动态池逐笔提取质量.json',B/'逐笔执行冻结方案.json',
           B/'动态池单位收益与风险.parquet',B/'动态池单位筛查完整性.json',B/'动态池风险档案核验清单.json',
           H/'2026一秒观察对照.json',H/'2026一秒观察已核验机会.parquet',H/'2026中间批次风险算术核验.json',
           H/'2026本地风险来源核验.json',H/'2026本地风险独立核验.json',H/'本地风险补验方案.md']
    OUT.mkdir()
    for f in files:shutil.copy2(f,OUT/f.name);assert sha(f)==sha(OUT/f.name)
    z={'all_checks_pass':True,'groups_processed':13,'groups_total':35,'original_source_unknown':4,'archive_pending':22,
       'risk_verified_unit_opportunities_per_leverage':4,'public_tape_sample_audit_complete':False,
       'files':{f.name:sha(OUT/f.name) for f in files},'note':'Same non-random size-ordered partial data; no strategy-performance conclusion.'}
    (OUT/'中间快照哈希.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_PARTIAL_V2_FROZEN',json.dumps({k:v for k,v in z.items() if k!='files'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
