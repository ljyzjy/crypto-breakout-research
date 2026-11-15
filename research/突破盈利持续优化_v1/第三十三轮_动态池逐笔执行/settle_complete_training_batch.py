"""Run the unchanged risk/funding logic against a clearly labeled training-only batch."""
import sys
from pathlib import Path
import settle_dynamic_paths as engine
import describe_incomplete_paths as diagnosis
HERE=Path(__file__).resolve().parent;OUT=HERE/'训练期分批'
engine.HERE=OUT;engine.WORK=engine.ROOT/'work'/'point_in_time_universe33'/'risk_training';engine.WORK.mkdir(parents=True,exist_ok=True)
engine.main()
quality=OUT/'动态池单位筛查完整性.json'
if quality.exists() and (OUT/'动态池单位收益与风险.parquet').exists():
    diagnosis.HERE=OUT;diagnosis.main()
