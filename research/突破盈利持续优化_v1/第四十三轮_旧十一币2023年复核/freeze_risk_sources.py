"""Freeze previously collected 2023 mark and funding inputs, including repair provenance."""
import hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;D=ROOT/'work'/'breakout_2023_11'/'normalized'
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths={f'{s}_{k}.parquet':D/f'{s}_{k}.parquet' for s in SYMBOLS for k in ('markPriceKlines','fundingRate')}
paths.update({'official_manifest.json':P/'第二轮_成本空间与即时成交'/'2023公开档案校验清单.json',
              'repair_manifest.json':P/'第二轮_成本空间与即时成交'/'2023日档修复记录.json'})
out={'plan_sha256':sha(H/'冻结研究方案.md'),'sources':{}}
for name,p in paths.items():
    assert p.is_file();out['sources'][name]={'path':str(p),'sha256':sha(p)}
dest=H/'风险来源冻结哈希.json'
if dest.exists():assert json.loads(dest.read_text(encoding='utf-8'))==out
else:dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('OLD11_2023_RISK_SOURCES_FROZEN',len(paths),flush=True)
