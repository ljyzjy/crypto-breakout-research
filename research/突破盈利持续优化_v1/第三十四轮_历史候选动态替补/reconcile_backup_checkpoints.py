"""Apply the same frozen raw-trade reconciliation to backup-only candidates."""
import hashlib,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
ORIG=PARENT/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG))
import reconcile_completed_checkpoints as engine
engine.HERE=HERE;engine.SOURCE=HERE/'替补独有潜在触价.parquet'
engine.ORIGINAL=ROOT/'work'/'point_in_time_universe34'/'tape'
engine.WORK=ROOT/'work'/'point_in_time_universe34'/'raw_reconciliation';engine.WORK.mkdir(parents=True,exist_ok=True)
engine.FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+(ORIG/'reconcile_completed_checkpoints.py').read_bytes()+
                   (ORIG/'raw_reconciliation.py').read_bytes()+(ORIG/'原始成交差异复核规则.json').read_bytes()+engine.SOURCE.read_bytes()).hexdigest()
engine.main()
