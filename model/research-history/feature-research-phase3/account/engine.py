"""Single minute strategy; event ordering and costs explicit, no order API."""
from dataclasses import dataclass,asdict
from collections import Counter
import math
import numpy as np
import pandas as pd
from pathlib import Path
import json
from market_io import load_quarantine
from account_market import Market,RankTrendGuard
ROOT=Path(__file__).resolve().parent
def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")

MINUTE=60_000
PRICE_COLS=['open','high','low','close','volume','quote_volume']

@dataclass
class Position:
    symbol:str;contract:str;side:int;qty:float;entry_ts:int;signal_ts:int
    raw_entry:float;entry:float;margin:float;stop:float;target:float
    entry_fee:float;entry_slip:float;funding:float=0.;last_mark:float=0.
    score:float=0.;rank:int=0;planned_risk:float=0.
    observation_id:str='';risk_multiplier:float=1.

def metrics(curve,trades,initial=1000.):
    if curve.empty:return {}
    last=float(curve.equity.iloc[-1]);days=(curve.ts.iloc[-1]-curve.ts.iloc[0]+MINUTE)/86_400_000
    ret=100*(last/initial-1);peak=np.maximum.accumulate(np.r_[initial,curve.equity.to_numpy()])[1:]
    dd=100*(1-curve.equity.to_numpy()/peak)
    t=pd.DataFrame(trades)
    return {'initial':initial,'final_equity':last,'return_pct':ret,
        'annualized_return_pct':100*((last/initial)**(365/days)-1) if days>=365 and last>0 else None,
        'elapsed_days':float(days),'max_drawdown':float(dd.max()),'trades':len(t),
        'win_rate':float(100*t.net.gt(0).mean()) if len(t) else 0.,
        'gross_pnl':float(t.gross.sum()) if len(t) else 0.,'fees':float(t.fees.sum()) if len(t) else 0.,
        'slippage_cost':float(t.slippage.sum()) if len(t) else 0.,'funding_cost':float(t.funding.sum()) if len(t) else 0.,
        'net_pnl':last-initial,'average_trade_net':float(t.net.mean()) if len(t) else 0.,
        'mean_holding_minutes':float(t.holding_minutes.mean()) if len(t) else 0.,
        'mean_exposure_pct':float(curve.exposure.mean()),
        'profit_factor':float(t.loc[t.net>0,'net'].sum()/-t.loc[t.net<0,'net'].sum()) if len(t) and t.net.lt(0).any() else None,
        'ledger_error':float(last-initial-t.net.sum()) if len(t) else float(last-initial)}

def simulate(scenario,signals,start,end,market=None,guard=None,save=True,run_id="baseline"):
    """Preserved original accounting/protection; injected frozen signal cohort."""
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    hi=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    fee=scenario['fee'];slip=scenario['slippage'];delay=scenario['delay_minutes']
    candidates=signals.copy()
    candidates['exec_ts']=candidates.ts+delay*MINUTE
    candidates=candidates[candidates.exec_ts.ge(lo)&candidates.exec_ts.lt(hi)].copy()
    candidates['strength']=candidates.score.abs()
    if 'liquidity_rank' not in candidates:candidates['liquidity_rank']=999
    candidates=candidates.sort_values(['exec_ts','strength','liquidity_rank','symbol'],ascending=[True,False,True,True])
    events={int(ts):list(g.to_dict('records')) for ts,g in candidates.groupby('exec_ts',sort=False)}
    guard=guard or RankTrendGuard();market=market or Market();cash=1000.;positions={};trades=[];audits=[];issues=[]
    cooldown={};blocked_until=lo;peak=1000.;known_equity=1000.;day_start=1000.;current_day=None
    daily_paused=False;permanent_pause=False;pause_ts=None;daily_entries=0;reason_counts=Counter()
    rows=[];worst_stress=0.;total_minutes=(hi-lo)//MINUTE
    quarantine=load_quarantine();funding_events=[]

    def close(p,raw,ts,reason,ambiguous=False):
        nonlocal cash,blocked_until
        fill=raw*(1-p.side*slip)
        exitfee=p.qty*fill*fee;exit_slip=p.qty*abs(fill-raw)
        pnl=p.side*p.qty*(fill-p.entry)
        cash+=p.margin+pnl-exitfee
        gross=p.side*p.qty*(raw-p.raw_entry)
        net=gross-p.entry_slip-exit_slip-p.entry_fee-exitfee-p.funding
        trades.append({'symbol':p.symbol,'contract':p.contract,'side':'long' if p.side==1 else 'short',
          'observation_id':p.observation_id,'risk_multiplier':p.risk_multiplier,
          'signal_ts':p.signal_ts,'decision_ts':p.signal_ts,'entry_ts':p.entry_ts,'exit_ts':int(ts),'raw_entry':p.raw_entry,'raw_exit':raw,'entry':p.entry,'exit':fill,'qty':p.qty,
          'entry_fee':p.entry_fee,'exit_fee':exitfee,'entry_slippage':p.entry_slip,'exit_slippage':exit_slip,
          'reason':reason,'ambiguous':ambiguous,'gross':gross,'fees':p.entry_fee+exitfee,
          'slippage':p.entry_slip+exit_slip,'funding':p.funding,'net':net,
          'stop':p.stop,'target':p.target,'entry_notional':p.qty*p.entry,'holding_minutes':(ts-p.entry_ts)/MINUTE,'rank':p.rank,'score':p.score,'planned_risk':p.planned_risk})
        cooldown[p.symbol]=int(ts)+60*MINUTE
        blocked_until=max(blocked_until,int(ts//MINUTE*MINUTE)+MINUTE)
        del positions[p.symbol]

    try:
        for n,ts in enumerate(range(lo,hi,MINUTE)):
            market.change_month(ts)
            beijing=(ts//MINUTE+480);day=beijing//1440;minute=beijing%1440
            was_active=bool(positions)
            if day!=current_day:
                current_day=day;day_start=known_equity;daily_paused=False;daily_entries=0
            if known_equity<=day_start*.985:daily_paused=True
            dd_known=1-known_equity/peak
            if dd_known>=.08 and not permanent_pause:permanent_pause=True;pause_ts=ts
            # Scheduled exits at this minute open use previously available information.
            for p in list(positions.values()):
                b=market.bar(p.contract,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                if not market.funding_ok(p.contract,ts):raise ValueError(f'held_funding_coverage_missing:{p.symbol}:{ts}')
                stop_hit=(b[0]<=p.stop if p.side==1 else b[0]>=p.stop)
                target_hit=(b[0]>=p.target if p.side==1 else b[0]<=p.target)
                why=('gap_stop' if stop_hit else 'gap_target' if target_hit else
                     'account_pause' if permanent_pause else 'daily_pause' if daily_paused else
                     'day_close' if minute>=1435 else 'time60' if ts-p.entry_ts>=60*MINUTE else None)
                if why:
                    # Settlement at an open boundary is ambiguous: debit only, no income credit.
                    for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                        signed=p.side*p.qty*m[0]*rate;charge=max(0.,signed);cash-=charge;p.funding+=charge
                        funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':p.qty,'side':p.side,'signed_charge':signed,'actual_charge':charge,'boundary_ambiguous':True})
                    close(p,float(b[0]),ts,why)
            if ts in events:
                for r in events[ts]:
                    s=r['symbol'];c=r['contract'];side=int(r['side'])
                    rejected=None
                    if permanent_pause:rejected='account_pause'
                    elif daily_paused:rejected='daily_pause'
                    elif minute>=1320:rejected='late_day'
                    elif ts<blocked_until:rejected='exit_wait'
                    elif len(positions)>=2:rejected='slots_full'
                    elif s in positions:rejected='already_held'
                    elif ts<cooldown.get(s,0):rejected='symbol_cooldown'
                    elif ts>=quarantine.get(s,{}).get('known_ts',10**18):rejected='known_quarantine'
                    if rejected:reason_counts[rejected]+=1;continue
                    if not guard.eligible(s,side,ts):reason_counts['pool_changed']+=1;continue
                    # Recheck current known minute after an added execution delay.
                    prev=market.bar(c,ts-MINUTE);prem=market.bar(c,ts-MINUTE,True)
                    if prev is None or prem is None or prev[4]<=0:reason_counts['prior_data_unusable']+=1;continue
                    b=market.bar(c,ts);m=market.bar(c,ts,True)
                    if b is None or m is None:raise ValueError(f'entry_execution_missing:{s}:{ts}')
                    price=float(b[0])*(1+side*slip);distance=side*(price-float(r['stop_price']));stopfrac=distance/price
                    signal_distance=side*(float(r['signal_close'])-float(r['stop_price']))
                    if side*(price-float(r['signal_close']))>.25*float(r['atr']):reason_counts['entry_deviation']+=1;continue
                    if distance<=0 or distance>1.5*float(r['atr']) or 2*stopfrac<.006 or 2*signal_distance/float(r['signal_close'])<.006:
                        reason_counts['stop_or_cost_gate']+=1;continue
                    risk_fraction=(.00125 if dd_known>=.05 else .0025)*float(r.get('risk_multiplier',1.))
                    if not (0<float(r.get('risk_multiplier',1.))<=1):raise ValueError('invalid_risk_multiplier')
                    equity=cash+sum(p.margin+p.side*p.qty*(p.last_mark-p.entry) for p in positions.values())
                    existing_risk=sum(p.qty*(max(0.,p.side*(p.last_mark-p.stop))+p.stop*(fee+slip)) for p in positions.values())
                    portfolio_cap=.005
                    for other in positions.values():
                        rho=guard.correlation(s,side,other.symbol,other.side,ts)
                        if rho is None or rho>.8:portfolio_cap=.0025
                    allowance=max(0.,min(equity*risk_fraction,equity*portfolio_cap-existing_risk))
                    gross_existing=sum(p.qty*p.last_mark for p in positions.values())
                    amount=min(allowance/(stopfrac+2*fee+2*slip),.5*equity,
                               max(0.,equity-gross_existing),cash/(1+fee),.001*float(prev[5]))
                    if amount<10:reason_counts['risk_or_liquidity_budget']+=1;continue
                    qty=amount/price;entryfee=amount*fee
                    stop=price-side*distance;target=price+side*2*distance
                    if min(stop,target)<=0:reason_counts['invalid_levels']+=1;continue
                    planned=amount*(stopfrac+2*fee+2*slip)
                    decision_ts=int(r.get('decision_ts',int(r['ts'])-MINUTE))
                    if decision_ts+MINUTE>ts:raise ValueError('noncausal_signal_arrival')
                    p=Position(s,c,side,qty,ts,decision_ts,float(b[0]),price,amount,stop,target,
                               entryfee,qty*abs(price-float(b[0])),last_mark=float(prem[3]),score=float(r['score']),rank=int(r['rank']),planned_risk=planned,
                               observation_id=str(r.get('observation_id','')),risk_multiplier=float(r.get('risk_multiplier',1.)))
                    positions[s]=p;cash-=amount+entryfee;daily_entries+=1;was_active=True
                    audits.append({'ts':ts,'signal_ts':decision_ts,'decision_ts':decision_ts,'observation_id':str(r.get('observation_id','')),'feature_known_ts':int(r.get('feature_known_ts',decision_ts)),'risk_multiplier':float(r.get('risk_multiplier',1.)),'symbol':s,'side':side,'rank':int(r['rank']),
                       'score':float(r['score']),'rvol':float(r['rvol']),'break_ts':int(r['break_ts']),'touch_ts':int(r['touch_ts']),'stop':stop,'target':target,'portfolio_risk_cap':portfolio_cap,'known_equity':equity,'notional':amount,'risk_fraction':risk_fraction,
                       'planned_loss':planned,'aggregate_planned_loss':existing_risk+planned,'gross_after':gross_existing+amount,
                       'previous_quote_volume':float(prev[5]),'slots':len(positions),'day_entries':daily_entries})
            # Audit funding coverage, then settle and process conservative intraminute exits.
            stress_equity=cash
            for p in positions.values():
                m=market.bar(p.contract,ts,True)
                if m is None:raise ValueError(f'held_missing_mark:{p.symbol}:{ts}')
                b=market.bar(p.contract,ts)
                if b is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                adverse=m[2] if p.side==1 else m[1]
                stress_equity+=p.margin+p.side*p.qty*(adverse-p.entry)
                sh=b[2]<=p.stop if p.side==1 else b[1]>=p.stop
                th=b[1]>=p.target if p.side==1 else b[2]<=p.target
                for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                    charge=p.side*p.qty*m[0]*rate
                    if p.entry_ts==ts or sh or th:charge=max(0.,charge)
                    stress_equity-=charge
            worst_stress=max(worst_stress,100*(1-stress_equity/peak))
            for p in list(positions.values()):
                b=market.bar(p.contract,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                if not market.funding_ok(p.contract,ts):raise ValueError(f'held_funding_coverage_missing:{p.symbol}:{ts}')
                sh=b[2]<=p.stop if p.side==1 else b[1]>=p.stop
                th=b[1]>=p.target if p.side==1 else b[2]<=p.target
                for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                    charge=p.side*p.qty*m[0]*rate
                    if p.entry_ts==ts or sh or th:charge=max(0.,charge)
                    cash-=charge;p.funding+=charge
                    funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':p.qty,'side':p.side,'signed_charge':p.side*p.qty*m[0]*rate,'actual_charge':charge,'boundary_ambiguous':bool(p.entry_ts==ts or sh or th)})
                if sh or th:
                    close(p,p.stop if sh else p.target,ts+MINUTE,'stop' if sh else 'target',bool(sh and th))
                else:p.last_mark=float(m[3])
            if ts==hi-MINUTE:
                for p in list(positions.values()):close(p,float(market.bar(p.contract,ts)[3]),ts+MINUTE,'period_end')
            known_equity=cash+sum(p.margin+p.side*p.qty*(p.last_mark-p.entry) for p in positions.values())
            peak=max(peak,known_equity)
            exposure=100*sum(p.qty*p.last_mark for p in positions.values())/known_equity if known_equity>0 else 0.
            rows.append((ts+MINUTE,known_equity,100*(1-known_equity/peak),exposure,len(positions),was_active,daily_paused,permanent_pause))
            if cash<-.000001:raise ValueError(f'negative_cash:{ts}')
            if n and n%150000==0:print('SIM',scenario['id'],n,'/',total_minutes,flush=True)
    except ValueError as exc:
        issues.append(str(exc))
    curve=pd.DataFrame(rows,columns=['ts','equity','drawdown','exposure','positions','active_in_minute','daily_paused','permanent_paused'])
    summary=metrics(curve,trades)
    summary.update(scenario=scenario['id'],start=start,end=end,fee=fee,slippage=slip,delay_minutes=delay,
        valid_for_comparison=not issues,issues=issues,intrabar_stress_dd=worst_stress,
        permanent_pause_ts=pause_ts,rejection_counts=dict(reason_counts),signal_candidates=len(candidates),
        leverage_cap=1,seconds_execution_verified=False,run_id=run_id,
        expected_calendar_minutes=int(total_minutes),observed_calendar_minutes=len(curve),
        active_minutes=int(curve.active_in_minute.sum()) if len(curve) else 0,
        cash_minutes=int((~curve.active_in_minute).sum()) if len(curve) else 0,
        permanent_halt_minutes=int(curve.permanent_paused.sum()) if len(curve) else 0,
        cash_days=float((~curve.active_in_minute).sum()/1440) if len(curve) else 0.,
        halted_days=float(curve.permanent_paused.sum()/1440) if len(curve) else 0.)
    summary['valid_for_comparison']=bool(not issues and len(curve)==total_minutes)
    if save:
        out=ROOT/'results'/run_id;out.mkdir(exist_ok=True,parents=True)
        curve.to_parquet(out/(scenario['id']+'-curve.parquet'),index=False)
        dump(out/(scenario['id']+'-trades.json'),trades)
        dump(out/(scenario['id']+'-entries.json'),audits)
        dump(out/(scenario['id']+'-funding.json'),funding_events)
        dump(out/(scenario['id']+'-summary.json'),summary)
    return summary,curve,trades,audits,funding_events

