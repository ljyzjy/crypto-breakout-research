from pathlib import Path
import sys,json,hashlib
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent;OLD=ROOT.parent/'coin-lab-v1'
sys.path.insert(0,str(OLD));import automatic_engine as old

def aggregate(rows,field):
    out=[]
    for key,g in rows.groupby(field,dropna=False):
        out.append({'group':str(key),'trades':len(g),'net':float(g.pnl.sum()),'gross':float(g.gross_pnl.sum()),'fees':float(g.fees.sum()),'slippage':float(g.slippage.sum()),'win_rate':float(g.pnl.gt(0).mean()*100),'mean_hold_hours':float(g.hold_hours.mean()),'mean_stake':float(g.stake.mean())})
    return out

def main():
    baseline=old.cached_run('2025-01-01','2026-10-31','auto_budget2',.001,'5m',0)
    daily=old.daily();factors,trace,_=old.rankings();idx=pd.date_range('2024-09-01','2026-10-31',tz='UTC')
    close={s:g.set_index('date').close.reindex(idx) for s,g in daily.groupby('symbol')}
    btc30=close['BTCUSDT']/close['BTCUSDT'].shift(30)-1;selection={r['date']:r for r in baseline['selection_trace']}
    trades=sorted(baseline['trades'],key=lambda t:(t['entry_ts'],t['symbol']));last={};detail=[]
    for t in trades:
        row=dict(t);s=t['symbol'];entry=pd.Timestamp(t['entry_ts'],unit='s',tz='UTC');prior=entry.normalize()-pd.Timedelta(days=1)
        sigma=float(factors[s].loc[prior,'sigma']);mom7=float(close[s].loc[prior]/close[s].shift(7).loc[prior]-1)
        week=(entry.normalize()-pd.Timedelta(days=entry.weekday())).strftime('%Y-%m-%d')
        prev=last.get(s);row['entry_kind']='repeat_after_stop_same_week' if prev and prev['reason'] in ('stop_loss','gap_stop') and prev['week']==week else 'other_entry'
        row['week']=week;row['momentum7']=mom7;row['momentum7_sign']='nonpositive' if mom7<=0 else 'positive'
        row['sigma']=sigma;row['sigma_group']='below2pct' if sigma<.02 else '2to4pct' if sigma<.04 else 'at_least4pct'
        row['market_direction']='BTC30_positive' if btc30.loc[prior]>0 else 'BTC30_nonpositive'
        reason=t['reason'];exitday=pd.Timestamp(t['exit_ts'],unit='s',tz='UTC').strftime('%Y-%m-%d')
        if reason=='signal_exit':reason='weekly_selection_removed' if s not in selection[exitday]['selected'] else 'daily_momentum_exit'
        row['exit_category']=reason
        prices=old.execution_data(s,'5m');held=prices.loc[entry:pd.Timestamp(t['exit_ts']-1,unit='s',tz='UTC')]
        row['mfe_pct']=float((held.high.max()/t['entry_price']-1)*100) if len(held) else 0.
        row['mae_pct']=float((held.low.min()/t['entry_price']-1)*100) if len(held) else 0.
        detail.append(row);last[s]=row
    d=pd.DataFrame(detail);d.to_csv(ROOT/'baseline_trade_diagnosis.csv',index=False,encoding='utf-8-sig')
    assert abs(d.pnl.sum()-(baseline['final_equity']-1000))<1e-7
    assert abs(d.gross_pnl.sum()-d.fees.sum()-d.slippage.sum()-d.pnl.sum())<1e-7
    groups={key:aggregate(d,key) for key in ['exit_category','symbol','entry_kind','momentum7_sign','sigma_group','market_direction']}
    groups['symbol'].sort(key=lambda r:r['net'])
    out={'baseline':{k:baseline[k] for k in ['id','return_pct','annualized_return_pct','max_drawdown','trade_count','fees','slippage_cost','gross_pnl','mean_exposure_pct','guard_activations','blocked_entry_signals']},'groups':groups,
         'holding_excursions':{'stop_trades':int(d.reason.eq('stop_loss').sum()),'stop_median_hours':float(d.loc[d.reason.eq('stop_loss'),'hold_hours'].median()),'stop_median_mfe_pct':float(d.loc[d.reason.eq('stop_loss'),'mfe_pct'].median())},
         'interpretation':'Descriptive decompositions, not independent causal estimates. Outcome excursions never feed signals. Cutoff choices registered in diagnosis_protocol.json before execution.'}
    old.base.dump(ROOT/'diagnosis.json',out)
    print(json.dumps({k:v for k,v in out.items() if k!='groups'},ensure_ascii=True))
    for k,v in groups.items():print(k,json.dumps(v if k!='symbol' else v[:5]+v[-5:],ensure_ascii=True))

if __name__=='__main__':main()
