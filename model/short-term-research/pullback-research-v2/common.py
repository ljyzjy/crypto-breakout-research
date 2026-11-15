from pathlib import Path
import json, hashlib, sys, importlib.util
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'minute-intraday-v1'
def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
sys.path.append(str(SOURCE))
spec=importlib.util.spec_from_file_location('previous_features',SOURCE/'features.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
load_contract=previous.load_contract
