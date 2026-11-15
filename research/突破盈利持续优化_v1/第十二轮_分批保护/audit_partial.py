"""Independently reconcile both exit legs and control against previous engine."""
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
CURVES=ROOT/'work'/'breakout_profit_research'/'curves'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def main():
    accounts=trades=partials=funds=0;parity=[]
    for sp in HERE.glob('train_*_summary.json'):
        stem=sp.name.removesuffix('_summary.json');sm=read(sp)
        ts=read(HERE/f'{stem}_trades.json');es=read(HERE/f'{stem}_entries.json');fs=read(HERE/f'{stem}_funding.json')
        assert sm['valid_for_comparison'] and len(ts)==len(es)==sm['trades']
        assert near(sum(t['net'] for t in ts),sm['net_pnl'])
        assert near(sum(t['funding'] for t in ts),sum(f['actual_charge'] for f in fs))
        fee=sm['fee'];slip=sm['slippage'];shock=sm['stop_shock']
        entry_by_id={e['observation_id']:e for e in es}
        assert len(entry_by_id)==len(es)
        for t in ts:
            e=entry_by_id[t['observation_id']]
            side=1 if t['side']=='long' else -1;q=t['qty'];part=t['partial_qty'];end=q-part
            assert 0<=part<=q and near(t['entry_fee'],q*t['entry']*fee)
            assert near(t['entry'],t['raw_entry']*(1+side*slip))
            assert near(t['entry_notional'],q*t['entry']) and near(t['isolated_margin'],t['entry_notional']/t['leverage'])
            assert near(t['planned_risk'],e['planned_loss']) and t['entry_ts']>=t['decision_ts']+5000
            assert near(t['final_fill'],t['final_raw_exit']*(1-side*(slip+(shock if t['reason'] in ('stop','gap_stop') else 0))))
            assert near(t['final_exit_fee'],end*t['final_fill']*fee+t['liquidation_penalty'])
            assert near(t['final_exit_slip'],end*abs(t['final_fill']-t['final_raw_exit']))
            if part:
                partials+=1
                assert near(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+60_000
                assert t['partial_ts']>=t['partial_effective_ts'] and t['partial_ts']<t['exit_ts']
                assert near(t['partial_fill'],t['partial_raw_exit']*(1-side*slip))
                assert near(t['partial_exit_fee'],part*t['partial_fill']*fee)
                assert near(t['partial_exit_slip'],part*abs(t['partial_fill']-t['partial_raw_exit']))
                assert near(t['stop'],t['entry']+side*.25*t['initial_price_risk'])
            else:assert t['partial_exit_fee']==t['partial_exit_slip']==0
            exitfee=t['partial_exit_fee']+t['final_exit_fee']
            expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-exitfee-t['funding']
            assert near(expected,t['net']) and near(exitfee,t['exit_fee'])
            assert near(t['raw_exit'],(part*t['partial_raw_exit']+end*t['final_raw_exit'])/q)
            assert near(t['exit'],(part*t['partial_fill']+end*t['final_fill'])/q)
        curve=pd.read_parquet(CURVES/f'{stem}.parquet',columns=['equity','active_in_minute'])
        assert len(curve)==sm['expected_calendar_minutes'] and near(curve.equity.iloc[-1],sm['final_equity'])
        dd=100*(1-curve.equity.to_numpy()/np.maximum.accumulate(np.r_[1000.,curve.equity.to_numpy()])[1:])
        assert near(dd.max(),sm['max_drawdown'])
        if '_control_' in stem:
            oldstem=stem.replace('_control_','_h4_')
            old=read(HERE.parent/'第九轮_突破后延长持仓'/f'{oldstem}_trades.json')
            assert len(old)==len(ts)
            for a,b in zip(ts,old):
                for k in ['observation_id','entry_ts','exit_ts','reason','net','qty','funding']:
                    assert (a[k]==b[k] if isinstance(a[k],str) else near(a[k],b[k])),(stem,k)
            parity.append(stem)
        accounts+=1;trades+=len(ts);funds+=len(fs)
    out={'accounts_checked':accounts,'trade_records_checked':trades,'partial_exits_checked':partials,
         'funding_events_checked':funds,'controls_identical_to_previous_engine':parity,
         'checked':'both leg prices, sizes, fees, slippage, delayed modification, funding, net, equity and drawdown'}
    (HERE/'分批账户独立对账.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PARTIAL_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
