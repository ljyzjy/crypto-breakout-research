"""Freeze ex-post big-candle evaluation before time-stop outcomes are available."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R100=P/'第一百轮_突破无进展提前退出'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True);assert not (R100/'进展退出结果汇总.json').exists() and not (H/'研究冻结.json').exists()
    sources=[H/'研究方案.md',R100/'研究冻结.json',R100/'time_stop.py',R100/'进展退出合成核验.json',
             bulk.R90/'二零二二日档补源质量.json',P/'第九十二轮_突破柱收益分解/突破柱分解独立核验.json']
    out={'frozen_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):bulk.sha(p) for p in sources},
         'label':'side * (quarter_close - quarter_open) >= ATR','raw_batch_fingerprint':bulk.fingerprint(),
         'note':'Completed-bar label is ex post only. Prior 2022 aggregate studies were already observed.'}
    (H/'研究冻结.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT102_FROZEN',out['frozen_utc'])


if __name__=='__main__':main()
