"""Apply the existing unit accounting to the frozen P15 pullback training slice."""
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ORIG=HERE.parent/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG))
import settle_dynamic_paths as engine
import describe_incomplete_paths as diagnosis
OUT=HERE/'训练期分批';engine.HERE=OUT;engine.WORK=engine.ROOT/'work'/'point_in_time_universe33'/'risk_pullback_training'
engine.WORK.mkdir(parents=True,exist_ok=True);engine.main()
if (OUT/'动态池单位筛查完整性.json').exists() and (OUT/'动态池单位收益与风险.parquet').exists():
    diagnosis.HERE=OUT;diagnosis.main()
