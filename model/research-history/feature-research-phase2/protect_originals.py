"""Read-only preservation check for prior research and simulator configuration."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def snapshot():
    paths=[]
    for folder in ('crypto-spot-kit','pullback-strategy-site','feature-research-phase1'):
        for p in (ROOT/'outputs'/folder).rglob('*'):
            if not p.is_file() or any(x in p.parts for x in ('node_modules','__pycache__','.git')):continue
            n=p.name.lower()
            if folder=='feature-research-phase1' or p.suffix in ('.py','.ps1','.jsx','.tsx','.html') or (p.suffix=='.json' and any(x in n for x in ('config','protocol','registration','frozen','comparison','validation','coverage'))):paths.append(p)
    return {str(p.relative_to(ROOT)).replace('\\','/'):{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(paths)}
if __name__=='__main__':
    if sys.argv[1]=='before':
        assert not (OUT/'protected_before.json').exists(),'Do not overwrite the initial preservation record'
        obj={'utc':datetime.now(timezone.utc).isoformat(),'files':snapshot(),'scope':'Previous source/configuration and research registration/results metadata. No live SQLite reads/writes. Market archive integrity is checked separately by data manifests.'}
        (OUT/'protected_before.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'protected_files':len(obj['files'])}))
    elif sys.argv[1]=='after':
        before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))['files'];after=snapshot()
        changed=[k for k,v in before.items() if after.get(k)!=v];added=[k for k in after if k not in before]
        obj={'utc':datetime.now(timezone.utc).isoformat(),'files_checked':len(before),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added,'backtests_executed':0,'paper_database_accessed':False}
        (OUT/'protection_validation.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(obj,ensure_ascii=True))
