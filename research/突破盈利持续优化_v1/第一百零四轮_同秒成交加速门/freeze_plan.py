"""Freeze the user-inspired same-phase tick-count rule before its evaluation."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R102=P/'第一百零二轮_大柱持有损益核查'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True);assert not (H/'研究冻结.json').exists()
    for path in (R98/'原始逐笔汇总独立核验.json',R98/'风险来源与账本独立核验.json',R102/'大柱标签独立核验.json'):
        assert json.loads(path.read_text(encoding='utf-8'))['all_checks_pass']
    d=pd.read_csv(R98/'候选状态与单位账本.csv');ids=sorted(d.loc[d.category.eq('trade'),'observation_id'].unique())
    assert len(ids)==133
    audit=sorted(ids,key=lambda x:hashlib.sha256(('same_phase_audit_v1|'+x).encode()).hexdigest())[:12]
    files=[H/'研究方案.md',R98/'研究冻结.json',R98/'run_raw_2022.py',R98/'原始逐笔汇总独立核验.json',
           R98/'候选状态与单位账本.csv',R98/'原始逐笔批次/逐笔信号.parquet',R102/'大柱标签独立核验.json',R102/'事后大柱标签.parquet']
    out={'frozen_utc':datetime.now(timezone.utc).isoformat(),'audit_sample_ids':audit,'lookback_candles':20,
         'threshold':'40*N >= 3*P','raw_batch_fingerprint':bulk.fingerprint(),
         'sources':{str(p):bulk.sha(p) for p in files},'note':'Raw and prior strategy results already observed. Historical exploratory filter, not a blind test.'}
    (H/'研究冻结.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT104_FROZEN',len(ids),len(audit),flush=True)


if __name__=='__main__':main()
