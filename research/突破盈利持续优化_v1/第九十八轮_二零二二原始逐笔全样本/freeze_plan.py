"""Freeze the raw tape population and hash-selected audit cases before bulk replay."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent; P=H.parent; R90=P/'第九十轮_二零二二公开行情'
sys.path.insert(0,str(R90)); import replay_2022 as runner


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    runner.guard(start=True); dest=H/'研究冻结.json'; assert not dest.exists()
    events=R90/'候选数据/固定十一币双币过滤潜在触价.parquet'; d=pd.read_parquet(events)
    assert len(d)==310 and d.observation_id.is_unique and len(d.groupby(['contract','day']))==284
    runner.verify_inputs()
    selected=sorted(d.observation_id, key=lambda x:hashlib.sha256(('2022_raw_audit_v1|'+x).encode()).hexdigest())[:12]
    files=[H/'研究方案.md',events,R90/'一秒逐笔独立样本核验.json',R90/'一秒逐笔回放进度.json',
           P/'第九十七轮_原始逐笔一秒回放试点/原始逐笔试点独立核验.json',
           P/'第六十二轮_一秒观察更早突破/one_second_observation.py',R90/'replay_2022.py']
    out={'frozen_utc':datetime.now(timezone.utc).isoformat(),'candidate_count':len(d),'group_count':284,
         'audit_sample_ids':selected,'selection':'first 12 by SHA256(2022_raw_audit_v1|observation_id)',
         'sources':{str(x):sha(x) for x in files},'source_fingerprint':runner.fingerprint(),
         'data_root':str(runner.ROOT),'note':'Prior year aggregate P&L and three raw pilot cases already viewed; not a blind study.'}
    dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print('EXT98_PLAN_FROZEN',len(d),len(selected))


if __name__=='__main__':main()
