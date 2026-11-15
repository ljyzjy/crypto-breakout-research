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
    initial_price_risk:float=0.;initial_stop:float=0.;break_level:float=0.;quarter_end_ts:int=0
    lock_known_ts:int=0;lock_effective_ts:int=0;lock_applied_ts:int=0;lock_done:bool=False
    failure_known_ts:int=0;failure_exit_ts:int=0
    leverage:float=1.
    execution_ts:int=0;entry_suffix:object=None
    initial_qty:float=0.;initial_margin:float=0.
    partial_qty:float=0.;partial_raw_exit:float=0.;partial_fill:float=0.
    partial_exit_fee:float=0.;partial_exit_slip:float=0.
    partial_known_ts:int=0;partial_effective_ts:int=0;partial_ts:int=0;partial_done:bool=False

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
    leverage=float(scenario['leverage']);maintenance=.005;liquidation_penalty=.005;gap_budget=.002
    stop_shock=float(scenario.get('stop_shock',0.))
    max_hold=int(scenario.get('max_hold_minutes',60));allow_overnight=bool(scenario.get('allow_overnight',False))
    if max_hold not in (60,240,720):raise ValueError('unsupported_hold_limit')
    if leverage not in (5.,10.,20.):raise ValueError('unsupported research leverage')
    candidates=signals.copy()
    candidates['exec_ts']=candidates.ts+delay*MINUTE
    candidates=candidates[candidates.exec_ts.ge(lo)&candidates.exec_ts.lt(hi)].copy()
    candidates['strength']=candidates.score.abs()
    if 'liquidity_rank' not in candidates:candidates['liquidity_rank']=999
    # Simultaneous signals enter in the order their assumed reference trades arrive.
    candidates['tick_sort']=pd.to_numeric(candidates.get('entry_exec_ts'),errors='coerce').fillna(np.inf)
    candidates=candidates.sort_values(['exec_ts','tick_sort','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
    events={int(ts):list(g.to_dict('records')) for ts,g in candidates.groupby('exec_ts',sort=False)}
    guard=guard or RankTrendGuard();market=market or Market();cash=1000.;positions={};trades=[];audits=[];issues=[]
    cooldown={};blocked_until=lo;peak=1000.;known_equity=1000.;day_start=1000.;current_day=None
    daily_paused=False;permanent_pause=False;pause_ts=None;daily_entries=0;reason_counts=Counter()
    rows=[];worst_stress=0.;total_minutes=(hi-lo)//MINUTE
    quarantine=load_quarantine();funding_events=[];rule_events=[]
    use_failure=bool(scenario.get('failure_exit',False));use_lock=bool(scenario.get('lock_profit',False))
    use_partial=bool(scenario.get('partial_exit',False))

    def close(p,raw,ts,reason,ambiguous=False):
        nonlocal cash,blocked_until
        extra_stop=stop_shock if reason in ('stop','gap_stop') else 0.
        fill=raw*(1-p.side*(slip+extra_stop))
        liquidation_fee=p.qty*fill*liquidation_penalty if reason.startswith('liquidation_proxy') else 0.
        final_exitfee=p.qty*fill*fee+liquidation_fee;final_exit_slip=p.qty*abs(fill-raw)
        pnl=p.side*p.qty*(fill-p.entry)
        cash+=p.margin+pnl-final_exitfee
        total_qty=p.initial_qty or p.qty
        weighted_raw=(p.partial_qty*p.partial_raw_exit+p.qty*raw)/total_qty
        weighted_fill=(p.partial_qty*p.partial_fill+p.qty*fill)/total_qty
        exitfee=p.partial_exit_fee+final_exitfee;exit_slip=p.partial_exit_slip+final_exit_slip
        gross=p.side*total_qty*(weighted_raw-p.raw_entry)
        net=gross-p.entry_slip-exit_slip-p.entry_fee-exitfee-p.funding
        trades.append({'symbol':p.symbol,'contract':p.contract,'side':'long' if p.side==1 else 'short',
          'observation_id':p.observation_id,'risk_multiplier':p.risk_multiplier,
          'signal_ts':p.signal_ts,'decision_ts':p.signal_ts,'entry_ts':p.execution_ts,'entry_bar_ts':p.entry_ts,'exit_ts':int(ts),'raw_entry':p.raw_entry,'raw_exit':weighted_raw,'entry':p.entry,'exit':weighted_fill,'qty':total_qty,
          'entry_fee':p.entry_fee,'exit_fee':exitfee,'entry_slippage':p.entry_slip,'exit_slippage':exit_slip,
          'reason':reason,'ambiguous':ambiguous,'gross':gross,'fees':p.entry_fee+exitfee,
          'slippage':p.entry_slip+exit_slip,'funding':p.funding,'net':net,
          'stop':p.stop,'target':p.target,'entry_notional':total_qty*p.entry,'holding_minutes':(ts-p.execution_ts)/MINUTE,'rank':p.rank,'score':p.score,'planned_risk':p.planned_risk,
          'initial_stop':p.initial_stop,'initial_price_risk':p.initial_price_risk,'break_level':p.break_level,
          'quarter_end_ts':p.quarter_end_ts,'lock_known_ts':p.lock_known_ts,'lock_applied_ts':p.lock_applied_ts,
          'failure_known_ts':p.failure_known_ts,'isolated_margin':p.initial_margin or p.margin,'leverage':p.leverage,
          'liquidation_penalty':liquidation_fee,'partial_qty':p.partial_qty,'partial_raw_exit':p.partial_raw_exit,
          'partial_fill':p.partial_fill,'partial_exit_fee':p.partial_exit_fee,'partial_exit_slip':p.partial_exit_slip,
          'partial_known_ts':p.partial_known_ts,'partial_effective_ts':p.partial_effective_ts,'partial_ts':p.partial_ts,
          'final_raw_exit':raw,'final_fill':fill,'final_exit_fee':final_exitfee,'final_exit_slip':final_exit_slip})
        cooldown[p.symbol]=int(ts)+60*MINUTE
        blocked_until=max(blocked_until,int(ts//MINUTE*MINUTE)+MINUTE)
        del positions[p.symbol]

    def liquidation_hit(p,mark):
        # Research proxy only; historical tiered maintenance/insurance rules are unavailable.
        balance=p.margin-p.entry_fee-max(p.funding,0.)+p.side*p.qty*(mark-p.entry)
        return balance <= p.qty*mark*(maintenance+liquidation_penalty)

    def position_bar(p,ts):
        if ts==p.entry_ts and p.entry_suffix is not None:return p.entry_suffix
        return market.bar(p.contract,ts)

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
                b=position_bar(p,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                if not market.funding_ok(p.contract,ts):raise ValueError(f'held_funding_coverage_missing:{p.symbol}:{ts}')
                if p.lock_effective_ts and not p.lock_done and ts>=p.lock_effective_ts:
                    previous_stop=p.stop;proposed=p.entry+p.side*.5*p.initial_price_risk
                    p.stop=max(p.stop,proposed) if p.side==1 else min(p.stop,proposed)
                    p.lock_done=True;p.lock_applied_ts=ts
                    rule_events.append({'id':p.observation_id,'kind':'lock_applied','known_ts':p.lock_known_ts,
                                        'effective_ts':ts,'old_stop':previous_stop,'new_stop':p.stop})
                stop_hit=(b[0]<=p.stop if p.side==1 else b[0]>=p.stop)
                target_hit=(b[0]>=p.target if p.side==1 else b[0]<=p.target)
                why=('liquidation_proxy_gap' if liquidation_hit(p,float(m[0])) else
                     'gap_stop' if stop_hit else 'gap_target' if target_hit else
                     'failed_breakout' if p.failure_exit_ts and ts>=p.failure_exit_ts else
                     'account_pause' if permanent_pause else 'daily_pause' if daily_paused else
                     'day_close' if minute>=1435 and not allow_overnight else
                     f'time{max_hold}' if ts-p.entry_ts>=max_hold*MINUTE else None)
                if why:
                    # Settlement at an open boundary is ambiguous: debit only, no income credit.
                    for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                        if ft<p.execution_ts:continue
                        signed=p.side*p.qty*m[0]*rate;charge=max(0.,signed);cash-=charge;p.funding+=charge
                        funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':p.qty,'side':p.side,'signed_charge':signed,'actual_charge':charge,'boundary_ambiguous':True})
                    close(p,float(b[0]),ts,why)
                    continue
                if use_partial and p.partial_effective_ts and not p.partial_done and ts>=p.partial_effective_ts:
                    proposed=p.entry+p.side*.25*p.initial_price_risk
                    previous_stop=p.stop
                    p.stop=max(p.stop,proposed) if p.side==1 else min(p.stop,proposed)
                    if p.side*(float(b[0])-p.stop)<=0:
                        # If the new protection is already crossed, close the whole position at this open.
                        for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                            if ft<p.execution_ts:continue
                            signed=p.side*p.qty*m[0]*rate;charge=max(0.,signed);cash-=charge;p.funding+=charge
                            funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':p.qty,'side':p.side,'signed_charge':signed,'actual_charge':charge,'boundary_ambiguous':True})
                        rule_events.append({'id':p.observation_id,'kind':'partial_gap_full_exit','known_ts':p.partial_known_ts,'effective_ts':ts,'old_stop':previous_stop,'new_stop':p.stop})
                        close(p,float(b[0]),ts,'gap_stop')
                        continue
                    part_qty=.5*p.qty;part_margin=.5*p.margin
                    # At an exact funding boundary, conservatively debit the part being sold.
                    for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                        if ft==ts and ft>=p.execution_ts:
                            signed=p.side*part_qty*m[0]*rate;charge=max(0.,signed);cash-=charge;p.funding+=charge
                            funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':part_qty,'side':p.side,'signed_charge':signed,'actual_charge':charge,'boundary_ambiguous':True,'partial_boundary':True})
                    part_raw=float(b[0]);part_fill=part_raw*(1-p.side*slip)
                    part_fee=part_qty*part_fill*fee;part_slip=part_qty*abs(part_fill-part_raw)
                    cash+=part_margin+p.side*part_qty*(part_fill-p.entry)-part_fee
                    p.qty-=part_qty;p.margin-=part_margin
                    p.partial_qty=part_qty;p.partial_raw_exit=part_raw;p.partial_fill=part_fill
                    p.partial_exit_fee=part_fee;p.partial_exit_slip=part_slip;p.partial_ts=ts;p.partial_done=True
                    rule_events.append({'id':p.observation_id,'kind':'partial_applied','known_ts':p.partial_known_ts,'effective_ts':ts,'old_stop':previous_stop,'new_stop':p.stop,'qty':part_qty,'raw_exit':part_raw})
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
                    if r.get('tick_status')!='verified':reason_counts['tick_unavailable']+=1;continue
                    execution_ts=int(r['entry_exec_ts']);raw_reference=float(r['raw_entry_5s'])
                    if not (ts<=execution_ts<ts+MINUTE and execution_ts>=int(r['decision_ts'])+5_000):raise ValueError('invalid_tick_execution_time')
                    suffix=np.array([raw_reference,float(r['suffix_high']),float(r['suffix_low']),float(r['suffix_close']),float(b[4]),float(b[5])])
                    if not np.isfinite(suffix[:4]).all() or suffix[1]<max(suffix[0],suffix[3]) or suffix[2]>min(suffix[0],suffix[3]):raise ValueError('invalid_tick_suffix')
                    price=raw_reference*(1+side*slip);distance=side*(price-float(r['stop_price']));stopfrac=distance/price
                    signal_distance=side*(float(r['signal_close'])-float(r['stop_price']))
                    if side*(price-float(r['signal_close']))>.25*float(r['atr']):reason_counts['entry_deviation']+=1;continue
                    if distance<=0 or distance>1.5*float(r['atr']) or 2*stopfrac<.006 or 2*signal_distance/float(r['signal_close'])<.006:
                        reason_counts['stop_or_cost_gate']+=1;continue
                    proxy_headroom=1./leverage-maintenance-liquidation_penalty
                    if proxy_headroom<=0 or stopfrac+gap_budget+fee+slip>=.5*proxy_headroom:
                        reason_counts['liquidation_buffer']+=1;continue
                    risk_fraction=(.00125 if dd_known>=.05 else .0025)*float(r.get('risk_multiplier',1.))
                    if not (0<float(r.get('risk_multiplier',1.))<=1):raise ValueError('invalid_risk_multiplier')
                    equity=cash+sum(p.margin+p.side*p.qty*(p.last_mark-p.entry) for p in positions.values())
                    existing_risk=sum(p.qty*(max(0.,p.side*(p.last_mark-p.stop))+p.last_mark*(fee+slip+gap_budget)) for p in positions.values())
                    portfolio_cap=.005
                    for other in positions.values():
                        rho=guard.correlation(s,side,other.symbol,other.side,ts)
                        if rho is None or rho>.8:portfolio_cap=.0025
                    allowance=max(0.,min(equity*risk_fraction,equity*portfolio_cap-existing_risk))
                    gross_existing=sum(p.qty*p.last_mark for p in positions.values())
                    amount=min(allowance/(stopfrac+2*fee+2*slip+gap_budget),equity,
                               max(0.,2*equity-gross_existing),cash/(1/leverage+fee),.001*float(prev[5]))
                    if amount<10:reason_counts['risk_or_liquidity_budget']+=1;continue
                    qty=amount/price;entryfee=amount*fee
                    stop=price-side*distance;target=price+side*float(scenario.get('target_r',2.))*distance
                    if min(stop,target)<=0:reason_counts['invalid_levels']+=1;continue
                    planned=amount*(stopfrac+2*fee+2*slip+gap_budget)
                    decision_ts=int(r.get('decision_ts',int(r['ts'])-MINUTE))
                    # Trigger may occur inside this minute or just before it;
                    # all pre-trigger filters were available at trigger-minute open.
                    if decision_ts+5_000>execution_ts:raise ValueError('noncausal_signal_arrival')
                    p=Position(s,c,side,qty,ts,decision_ts,raw_reference,price,amount/leverage,stop,target,
                               entryfee,qty*abs(price-raw_reference),last_mark=float(prem[3]),score=float(r['score']),rank=int(r['rank']),planned_risk=planned,
                               observation_id=str(r.get('observation_id','')),risk_multiplier=float(r.get('risk_multiplier',1.)),
                               initial_price_risk=distance,initial_stop=stop,break_level=float(r['level']),
                               quarter_end_ts=(int(r['break_ts'])//(15*MINUTE)+1)*(15*MINUTE),leverage=leverage,
                               execution_ts=execution_ts,entry_suffix=suffix,initial_qty=qty,initial_margin=amount/leverage)
                    if use_failure and ts==p.quarter_end_ts:
                        prev_quarter=market.bar(c,p.quarter_end_ts-MINUTE)
                        if prev_quarter is None:raise ValueError(f'missing_breakout_close:{s}:{ts}')
                        if side*(float(prev_quarter[3])-p.break_level)<=0:
                            p.failure_known_ts=p.quarter_end_ts;p.failure_exit_ts=p.quarter_end_ts+MINUTE
                            rule_events.append({'id':p.observation_id,'kind':'failure_scheduled',
                                                'known_ts':p.failure_known_ts,'effective_ts':p.failure_exit_ts,
                                                'close':float(prev_quarter[3]),'level':p.break_level})
                    positions[s]=p;cash-=amount/leverage+entryfee;daily_entries+=1;was_active=True
                    audits.append({'ts':ts,'execution_ts':execution_ts,'raw_entry_5s':raw_reference,'signal_ts':decision_ts,'decision_ts':decision_ts,'observation_id':str(r.get('observation_id','')),'feature_known_ts':int(r.get('feature_known_ts',decision_ts)),'risk_multiplier':float(r.get('risk_multiplier',1.)),'symbol':s,'side':side,'rank':int(r['rank']),
                       'score':float(r['score']),'rvol':float(r['rvol']),'break_ts':int(r['break_ts']),'touch_ts':int(r['touch_ts']),'stop':stop,'target':target,'portfolio_risk_cap':portfolio_cap,'known_equity':equity,'notional':amount,'risk_fraction':risk_fraction,
                       'planned_loss':planned,'aggregate_planned_loss':existing_risk+planned,'gross_after':gross_existing+amount,
                       'previous_quote_volume':float(prev[5]),'slots':len(positions),'day_entries':daily_entries})
            # Audit funding coverage, then settle and process conservative intraminute exits.
            stress_equity=cash
            for p in positions.values():
                m=market.bar(p.contract,ts,True)
                if m is None:raise ValueError(f'held_missing_mark:{p.symbol}:{ts}')
                b=position_bar(p,ts)
                if b is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                adverse=m[2] if p.side==1 else m[1]
                stress_equity+=p.margin+p.side*p.qty*(adverse-p.entry)
                sh=b[2]<=p.stop if p.side==1 else b[1]>=p.stop
                th=b[1]>=p.target if p.side==1 else b[2]<=p.target
                for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                    if ft<p.execution_ts:continue
                    charge=p.side*p.qty*m[0]*rate
                    if p.entry_ts==ts or sh or th:charge=max(0.,charge)
                    stress_equity-=charge
            worst_stress=max(worst_stress,100*(1-stress_equity/peak))
            for p in list(positions.values()):
                b=position_bar(p,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                if not market.funding_ok(p.contract,ts):raise ValueError(f'held_funding_coverage_missing:{p.symbol}:{ts}')
                sh=b[2]<=p.stop if p.side==1 else b[1]>=p.stop
                th=b[1]>=p.target if p.side==1 else b[2]<=p.target
                for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                    if ft<p.execution_ts:continue
                    charge=p.side*p.qty*m[0]*rate
                    if p.entry_ts==ts or sh or th:charge=max(0.,charge)
                    cash-=charge;p.funding+=charge
                    funding_events.append({'symbol':p.symbol,'entry_ts':p.entry_ts,'settlement_ts':ft,'minute_ts':ts,'rate':rate,'mark_open':float(m[0]),'qty':p.qty,'side':p.side,'signed_charge':p.side*p.qty*m[0]*rate,'actual_charge':charge,'boundary_ambiguous':bool(p.entry_ts==ts or sh or th)})
                adverse_mark=float(m[2] if p.side==1 else m[1])
                liq=liquidation_hit(p,adverse_mark)
                if liq:
                    # Within-minute sequence is unknown; liquidation takes priority for stress testing.
                    adverse_trade=float(b[2] if p.side==1 else b[1])
                    close(p,adverse_trade,ts+MINUTE,'liquidation_proxy',bool(sh or th))
                elif sh or th:
                    close(p,p.stop if sh else p.target,ts+MINUTE,'stop' if sh else 'target',bool(sh and th))
                else:
                    p.last_mark=float(m[3])
                    bar_known=ts+MINUTE
                    favorable=float(b[1] if p.side==1 else b[2])
                    if use_partial and not p.partial_known_ts and p.side*(favorable-p.entry)>=p.initial_price_risk:
                        p.partial_known_ts=bar_known;p.partial_effective_ts=bar_known+MINUTE
                        rule_events.append({'id':p.observation_id,'kind':'partial_scheduled','known_ts':bar_known,
                                            'effective_ts':p.partial_effective_ts,'favorable':favorable,'entry':p.entry,'initial_r':p.initial_price_risk})
                    if use_failure and not p.failure_known_ts and bar_known==p.quarter_end_ts and p.side*(float(b[3])-p.break_level)<=0:
                        p.failure_known_ts=bar_known;p.failure_exit_ts=bar_known+MINUTE
                        rule_events.append({'id':p.observation_id,'kind':'failure_scheduled',
                                            'known_ts':bar_known,'effective_ts':p.failure_exit_ts,
                                            'close':float(b[3]),'level':p.break_level})
                    if (use_lock and not p.lock_known_ts and bar_known%(5*MINUTE)==0 and
                        ts-4*MINUTE>=p.entry_ts and p.side*(float(b[3])-p.entry)>=p.initial_price_risk):
                        p.lock_known_ts=bar_known;p.lock_effective_ts=bar_known+MINUTE
                        rule_events.append({'id':p.observation_id,'kind':'lock_scheduled',
                                            'known_ts':bar_known,'effective_ts':p.lock_effective_ts,
                                            'close':float(b[3]),'entry':p.entry,'initial_r':p.initial_price_risk})
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
        account_gross_exposure_cap=2,position_leverage=leverage,seconds_execution_verified=False,run_id=run_id,rule_events=rule_events,
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

