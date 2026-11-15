"""Freeze candidate and audited execution inputs before descriptive labeling."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;R=P/'第四十七轮_一次重新突破确认';I=H/'冻结输入';I.mkdir(exist_ok=True)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    dest=H/'冻结输入哈希.json'
    if dest.exists():
        z=json.loads(dest.read_text(encoding='utf-8'));assert sha(H/'事后诊断方案.md')==z['plan_sha256']
        for n,v in z['inputs'].items():assert sha(I/n)==v
        return
    audit=R/'单次重试净账本独立核验.json';assert json.loads(audit.read_text(encoding='utf-8'))['all_checks_pass']
    sources={'comparison.json':R/'单次重试跨期单位对照.json','audit.json':audit,
             'minute_sources.json':P/'第四十六轮_固定十一加密币跨时段'/'小块来源冻结哈希.json'}
    for year in ('2024','2026'):
        sources[f'{year}_signal.parquet']=R/'跨期冻结输入'/f'{year}_signal.parquet'
        sources[f'{year}_baseline_ledger.parquet']=R/'跨期冻结输入'/f'{year}_ledger.parquet'
        sources[f'{year}_retry_ledger.parquet']=R/f'{year}重试分批'/'动态池单位收益与风险.parquet'
    for name,src in sources.items():
        dst=I/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    out={'plan_sha256':sha(H/'事后诊断方案.md'),'inputs':{n:sha(I/n) for n in sources},
         'note':'Post-close labels for descriptive capture only; no future data in entries.'}
    dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('CAPTURE53_INPUTS_FROZEN',flush=True)
if __name__=='__main__':main()
