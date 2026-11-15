from pathlib import Path
import json,hashlib,time
import coin_engine as c
ROOT=Path(__file__).resolve().parent
SCENARIOS=[('later','2025-01-01','2026-10-31',.001,'1h',0),('later','2025-01-01','2026-10-31',.001,'5m',0),('2025','2025-01-01','2025-12-31',.001,'5m',0),('2026','2026-01-01','2026-10-31',.001,'5m',0),('later','2025-01-01','2026-10-31',.002,'5m',0),('later','2025-01-01','2026-10-31',.003,'5m',0),('later','2025-01-01','2026-10-31',.001,'5m',5)]
def main():
    frozen={str(p.relative_to(ROOT.parent.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'protocol.json',ROOT/'automatic-protocol.json',ROOT/'coin_engine.py',ROOT/'run_sizing.py',ROOT.parent/'risk-budget-v1/risk_engine.py',ROOT.parent/'st_engine.py']}
    p=ROOT/'sizing-frozen.json'
    if p.exists():assert json.loads(p.read_text())==frozen
    else:p.write_text(json.dumps(frozen,indent=2),encoding='utf-8')
    rows=[]
    for policy in c.POLICIES:
        for window,start,end,fee,tf,delay in SCENARIOS:
            r=c.cached_run(start,end,policy,fee,tf,delay);r['window']=window;rows.append(c.summary(r))
            print(policy,window,tf,fee,delay,'ROI',round(r['return_pct'],4),'DD',round(r['max_drawdown'],4),flush=True)
    c.base.dump(ROOT/'sizing-metrics.json',rows)
    print('49 sizing scenarios complete',flush=True)
if __name__=='__main__':main()
