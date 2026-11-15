"""Final read-only preservation and local artifact integrity record."""
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, subprocess, sys
P=Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''): h.update(block)
    return h.hexdigest()
def dump(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
if '--manifest-only' not in sys.argv:
    subprocess.run([sys.executable,'-B',str(P/'protect_originals.py'),'after'],check=True)
    p2=P.parent/'feature-research-phase2'
    previous=read(p2/'freeze_manifest.json')['files']; bad=[]
    for rel,entry in previous.items():
        f=p2/rel
        if not f.is_file() or f.stat().st_size!=entry['size'] or sha(f)!=entry['sha256']:bad.append(rel)
    frozen=read(P/'registration_freeze.json')
    checks={'verified_utc':datetime.now(timezone.utc).isoformat(),'protocol_unchanged':sha(P/'protocol.json')==frozen['protocol_sha256'],
     'market_manifest_unchanged':sha(P/'account/market_manifest.json')==frozen['market_manifest_sha256'],
     'phase1_registration_unchanged':sha(P.parent/'feature-research-phase1/research_registration.json')==frozen['phase1_registration_sha256'],
     'phase2_freeze_manifest_unchanged':sha(p2/'freeze_manifest.json')==frozen['phase2_freeze_manifest_sha256'],
     'phase2_frozen_files_checked':len(previous),'phase2_changed_files':bad,
     'old_source_config_metadata_unchanged':read(P/'protection_validation.json')['unchanged'],
     'paper_database_accessed':False}
    checks['passed']=all(checks[k] for k in ['protocol_unchanged','market_manifest_unchanged','phase1_registration_unchanged','phase2_freeze_manifest_unchanged','old_source_config_metadata_unchanged']) and not bad
    dump(P/'integrity_validation.json',checks)
else: checks=read(P/'integrity_validation.json')
assert checks['passed'],checks
if '--check-only' in sys.argv:
    print(json.dumps(checks));sys.exit(0)
files={}
for f in sorted(P.rglob('*')):
    if not f.is_file() or '__pycache__' in f.parts or f.name in ('freeze_manifest.json',) or f.suffix in ('.log','.tmp'):continue
    files[f.relative_to(P).as_posix()]={'sha256':sha(f),'size':f.stat().st_size}
dump(P/'freeze_manifest.json',{'utc':datetime.now(timezone.utc).isoformat(),'scope':'Phase3 final deliverables; reused market inputs pinned transitively, no real-account certification. Logs excluded; no new outcomes period beyond frozen historical sample.','files':files})
print(json.dumps({'checks':checks,'phase3_files':len(files)}))
