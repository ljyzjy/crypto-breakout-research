"""Freeze audited source files before computing the single price-extension contrast."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'第四十九轮_固定主动方向强度';I=H/'冻结输入';I.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=H/'输入冻结哈希.json'
    if out.exists():
        z=json.loads(out.read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==z['plan_sha256']
        for n,v in z['inputs'].items():assert sha(I/n)==v
        return
    assert json.loads((P/'强方向筛选独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    old=json.loads((P/'输入冻结哈希.json').read_text(encoding='utf-8'));sources={n:P/'冻结输入'/n for n in old['inputs']}
    for name,src in sources.items():
        assert sha(src)==old['inputs'][name];dst=I/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    z={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in sources},
       'note':'One cost-anchored threshold fixed before this conditional comparison; earlier summaries were observed.'}
    out.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PRICE50_INPUTS_FROZEN',len(sources),flush=True)
if __name__=='__main__':main()
