"""Record existing 2023 market inputs and unchanged research-code fingerprints."""
import hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;DATA=ROOT/'work'/'breakout_2023_11'/'normalized'
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files={f'{s}_klines.parquet':DATA/f'{s}_klines.parquet' for s in SYMBOLS}
files.update({'raw_manifest.json':P/'第二轮_成本空间与即时成交'/'2023公开档案校验清单.json',
              'repair_manifest.json':P/'第二轮_成本空间与即时成交'/'2023日档修复记录.json',
              'original_minute_features.py':P/'第三十二轮_历史动态池分钟信号'/'minute_features.py',
              'hourly_indicators.py':P/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py',
              'market_filter.py':P/'第四十轮_BTC_ETH事前活跃度'/'market_decisions.py',
              'flow_research.py':P/'flow_research.py','minute_features_2023.py':H/'minute_features_2023.py'})
out={'plan_sha256':sha(H/'冻结研究方案.md'),'sources':{}}
for name,path in files.items():
    assert path.exists(),str(path);out['sources'][name]={'path':str(path),'sha256':sha(path)}
manifest=json.loads((P/'第二轮_成本空间与即时成交'/'2023公开档案校验清单.json').read_text(encoding='utf-8'))
assert manifest['verified']==manifest['expected'] and not manifest['issues']
repair=json.loads((P/'第二轮_成本空间与即时成交'/'2023日档修复记录.json').read_text(encoding='utf-8'))
assert repair['repaired_contracts']==11
target=H/'来源冻结哈希.json'
if target.exists():assert json.loads(target.read_text(encoding='utf-8'))==out
else:target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('OLD11_2023_SOURCES_FROZEN',len(files),flush=True)
