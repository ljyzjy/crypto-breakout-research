"""Freeze all sources before calculating the single flow-strength contrast."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'第四十七轮_一次重新突破确认';I=H/'冻结输入';I.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=H/'输入冻结哈希.json'
    if out.exists():
        z=json.loads(out.read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==z['plan_sha256']
        for n,v in z['inputs'].items():assert sha(I/n)==v
        return
    audit=P/'单次重试净账本独立核验.json';causal=P/'重试来源时序独立核验.json'
    assert json.loads(audit.read_text(encoding='utf-8'))['all_checks_pass'] and json.loads(causal.read_text(encoding='utf-8'))['all_checks_pass']
    sources={'retry_audit.json':audit,'causality_audit.json':causal}
    for year in ('2023','2024','2026'):
        root=P/('2023冻结输入' if year=='2023' else '跨期冻结输入')
        for name in ('signal','paths','ledger'):
            sources[f'{year}_baseline_{name}.parquet']=root/(f'baseline_{name}.parquet' if year=='2023' else f'{year}_{name}.parquet')
        R=P/f'{year}重试分批'
        for name,src in [('signal','动态池逐笔信号筛查.parquet'),('paths','动态池延迟市价路径.parquet'),('ledger','动态池单位收益与风险.parquet')]:
            sources[f'{year}_retry_{name}.parquet']=R/src
    for name,src in sources.items():
        dst=I/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    z={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in sources},
       'note':'Single threshold fixed after unstratified results, before this conditional analysis.'}
    out.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FLOW49_INPUTS_FROZEN',len(sources),flush=True)
if __name__=='__main__':main()
