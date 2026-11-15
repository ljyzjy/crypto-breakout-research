"""Record the one fixed cost-to-target rule before raw-2022 summaries exist."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True);bulk.frozen();assert not (R98/'原始逐笔汇总.json').exists();assert not (H/'研究冻结.json').exists()
    files=[H/'研究方案.md',R98/'研究冻结.json',R98/'run_raw_2022.py',R98/'批量回放试点一致性.json',
           R98/'build_batch.py',R98/'settle_risk.py',R98/'summarize.py']
    out={'frozen_utc':datetime.now(timezone.utc).isoformat(),'minimum_directional_stop_fraction':.004,
         'sources':{str(p):bulk.sha(p) for p in files},'raw_batch_fingerprint':bulk.fingerprint(),
         'note':'Earlier aggregate results and three pilot outcomes are known. Full raw 2022 summary not yet present; historical non-blind analysis.'}
    (H/'研究冻结.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT99_FROZEN',out['frozen_utc'])


if __name__=='__main__':main()
