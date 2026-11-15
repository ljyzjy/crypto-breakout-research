"""Generate later-period candidate minutes after both first-touch selections freeze."""
import hashlib
import json
from pathlib import Path

import generate_touch_candidates as gen

HERE=Path(__file__).resolve().parent
lead=HERE.parent/'第八轮_BTC短时领先'
checks=[(HERE/'柱内触价冻结候选.json',HERE/'冻结研究计划.json',HERE/'柱内触价训练候选对照.json'),
        (lead/'短时领先冻结候选.json',lead/'冻结研究计划.json',lead/'短时领先训练候选对照.json')]
for decision_path,plan_path,train_path in checks:
    decision=json.loads(decision_path.read_text(encoding='utf-8'))
    assert decision['selected'] and decision['plan_sha256']==hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert decision['training_sha256']==hashlib.sha256(train_path.read_bytes()).hexdigest()
if __name__=='__main__':
    gen.generate(2024,'2024-07-01','2024-12-31','2024h2')
    gen.generate(2026,'2026-08-01','2026-11-12','2026later')
    gen.generate(2023,'2023-01-01','2023-12-31','2023full')
    print('LATER_TOUCH_CANDIDATES_READY',flush=True)
