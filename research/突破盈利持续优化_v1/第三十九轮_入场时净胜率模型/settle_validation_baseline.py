"""Settle the baseline after frozen model decisions, keeping source unknowns."""
import sys
from pathlib import Path
H=Path(__file__).resolve().parent;O=H.parent/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(O))
import settle_dynamic_paths as engine
import describe_incomplete_paths as diagnosis
arg=sys.argv[1] if len(sys.argv)>1 else '2024'
assert arg in ('2024','2026')
out=H/('2024后续比较批次' if arg=='2024' else '2026后续比较批次')
engine.HERE=out;engine.WORK=engine.ROOT/'work'/'point_in_time_universe33'/('risk_model_validation_'+arg)
engine.WORK.mkdir(parents=True,exist_ok=True);engine.main()
if (out/'动态池单位筛查完整性.json').exists() and (out/'动态池单位收益与风险.parquet').exists():
    diagnosis.HERE=out;diagnosis.main()
