"""Freeze fixed-11 minute sources and the candidate-generation code."""
import hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
roots={2024:ROOT/'work'/'breakout_2024_11'/'normalized',2026:ROOT/'work'/'breakout_forward_2026'/'normalized'}
code={'prepare':H/'prepare_fixed11.py','minutes':H/'minute_features_fixed11.py',
      'hourly':P/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py','flow':P/'flow_research.py',
      'relaxed':P.parent/'大突破柱高杠杆研究_v1'/'放宽入场研究'/'run_relaxed.py',
      'leverage_study':P.parent/'大突破柱高杠杆研究_v1'/'run_leverage_study.py',
      'forward':P.parent/'突破胜率与净收益前瞻检验_v1'/'forward_research.py',
      'prior_features':P.parent/'突破柱融合研究_v1'/'research.py',
      'market_filter':P/'第四十轮_BTC_ETH事前活跃度'/'market_decisions.py'}
support={'2024_source_manifest':P/'2024公开档案校验清单.json',
         '2026_source_manifest':P.parent/'突破胜率与净收益前瞻检验_v1'/'公开数据校验清单.json'}
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(p):assert p.is_file(),str(p);return {'path':str(p),'sha256':sha(p)}
def main():
    sources={f'{year}_{symbol}':record(root/f'{symbol}_klines.parquet') for year,root in roots.items() for symbol in SYMBOLS}
    result={'plan_sha256':sha(H/'冻结研究方案.md'),'sources':sources,'code':{k:record(v) for k,v in code.items()},
            'support':{k:record(v) for k,v in support.items()},
            'note':'Existing 2024/2026 normalized public archives; fixed selection has survivorship bias.'}
    file=H/'来源冻结哈希.json'
    if file.exists():assert json.loads(file.read_text(encoding='utf-8'))==result
    else:file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_SOURCES_FROZEN',len(sources),'code',len(code),flush=True)
if __name__=='__main__':main()
