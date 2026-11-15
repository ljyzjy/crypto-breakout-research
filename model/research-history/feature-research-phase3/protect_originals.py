"""Protect previous research and simulator code without opening a paper database."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, sys
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def snapshot():
    old=json.loads((ROOT/'outputs/feature-research-phase2/protected_before.json').read_text(encoding='utf-8'))['files']
    paths={ROOT/p for p in old}
    for p in (ROOT/'outputs/feature-research-phase2').rglob('*'):
        if p.is_file() and p.suffix in ('.py','.json','.txt') and '__pycache__' not in p.parts:
            paths.add(p)
    return {p.relative_to(ROOT).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(paths)}
if __name__=='__main__':
    if sys.argv[1]=='before':
        assert not (OUT/'protected_before.json').exists()
        obj={'utc':datetime.now(timezone.utc).isoformat(),'files':snapshot(),'scope':'Original source/configuration plus Phase 1/2 metadata and code; market files independently verified by frozen source manifests; no paper database opened.'}
        (OUT/'protected_before.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'protected_files':len(obj['files'])}))
    elif sys.argv[1]=='after':
        before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))['files']; after=snapshot()
        changed=[k for k,v in before.items() if after.get(k)!=v]
        added=[k for k in after if k not in before]
        obj={'utc':datetime.now(timezone.utc).isoformat(),'files_checked':len(before),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added,'paper_database_accessed':False}
        (OUT/'protection_validation.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(obj))
