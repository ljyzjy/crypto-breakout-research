"""Use the unchanged risk and cost engine on an explicitly partial 2023 batch."""
from pathlib import Path
import settle_2023_engine as engine
import describe_2023_incomplete as diagnosis
H=Path(__file__).resolve().parent;O=H.parent/'第三十三轮_动态池逐笔执行';OUT=H/'部分批次'
old=(O/'settle_dynamic_paths.py').read_text(encoding='utf-8');new=(H/'settle_2023_engine.py').read_text(encoding='utf-8')
assert old[:old.index("    end=int(pd.Timestamp('2024-05-01'")]==new[:new.index("    print('OLD11_2023_RISK_COMPLETE'")]
engine.HERE=OUT;engine.WORK=engine.ROOT/'work'/'point_in_time_universe33'/'risk_old11_2023';engine.WORK.mkdir(parents=True,exist_ok=True)
engine.main()
if (OUT/'动态池单位筛查完整性.json').exists() and (OUT/'动态池单位收益与风险.parquet').exists():diagnosis.main()
