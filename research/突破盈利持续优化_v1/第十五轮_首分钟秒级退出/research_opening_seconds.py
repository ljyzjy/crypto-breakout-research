"""Apply the previously audited second-path simulator to first-minute events."""
import hashlib,importlib.util,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
source=PARENT/'第十四轮_首分钟逐笔突破'/'首分钟潜在候选_2026.parquet'
d=pd.read_parquet(source)
assert (d.trigger_minute==d.quarter_start).all() and d.observation_id.is_unique
d.to_parquet(HERE/'潜在触价候选_2026.parquet',index=False)
sp=importlib.util.spec_from_file_location('opening_seconds_impl',PARENT/'第七轮_秒级退出可行性'/'research_seconds_exit.py')
mod=importlib.util.module_from_spec(sp);sys.modules[sp.name]=mod;sp.loader.exec_module(mod)
mod.HERE=HERE;mod.TOUCH=HERE
OriginalPool=mod.concurrent.futures.ThreadPoolExecutor
class SmallPool(OriginalPool):
    def __init__(self,max_workers=None,**kwargs):super().__init__(max_workers=2,**kwargs)
mod.concurrent.futures.ThreadPoolExecutor=SmallPool
mod.main()
path=HERE/'秒级退出探索结果.json';out=json.loads(path.read_text(encoding='utf-8'))
out['plan_sha256']=hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
out['candidate_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
out['scope']='First minute of the 15-minute candle; earlier work used later trigger minutes.'
path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
