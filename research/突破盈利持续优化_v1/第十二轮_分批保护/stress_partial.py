"""Cost and leverage sensitivity for predeclared partial-exit variants."""
import gc,json
from pathlib import Path
import train_partial as t
flow=t.flow;HERE=Path(__file__).resolve().parent
def main():
    sig=t.touch.load_data();results=[]
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        t.r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=sig[sig.source_year.eq(str(year))].copy()
        for name,partial,target in t.VARIANTS:
            if not partial:continue
            for lev,scenario in [(10,'main'),(10,'stress'),(20,'stress')]:
                results.append(flow.simulate(subset,name,start,end,market,guard,lev,scenario,period,
                    target_override=target,max_hold_minutes=240,allow_overnight=True,partial_exit=True))
        del market,guard,subset;gc.collect()
    flow.dump(HERE/'分批方案杠杆及成本压力.json',results)
    print('PARTIAL_STRESS_COMPLETE',len(results),'valid',sum(s['valid_for_comparison'] for s in results),flush=True)
if __name__=='__main__':main()
