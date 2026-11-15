"""Freeze the prior fixed cost gate and previously studied period sources."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;P=H.parent;R95=P/'第九十五轮_扩充训练滚动预测';R99=P/'第九十九轮_成本相对波幅门'
sys.path.insert(0,str(R95));import run_expanded_walkforward as prior


def main():
    prior.guard.guard(start=True);assert not (H/'研究冻结.json').exists()
    proof=json.loads((R95/'扩充滚动模型独立核验.json').read_text(encoding='utf-8'));assert proof['all_checks_pass']
    f=json.loads((R99/'研究冻结.json').read_text(encoding='utf-8'));assert f['minimum_directional_stop_fraction']==.004
    for path,digest in f['sources'].items():assert prior.sha(Path(path))==digest
    files=[H/'研究方案.md',R99/'研究冻结.json',R95/'冻结时点.json',R95/'run_expanded_walkforward.py',
           R95/'扩充滚动模型独立核验.json',prior.R77/'冻结时点.json',prior.R77/'run_walkforward.py']
    out={'frozen_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(x):prior.sha(x) for x in files},
         'periods':['2023','2024','2026','2026_aug_oct'],'gate':.004,
         'note':'Threshold fixed before this calculation. All periods already studied; aggregate trades, non-blind.'}
    (H/'研究冻结.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT101_FROZEN',out['frozen_utc'])


if __name__=='__main__':main()
