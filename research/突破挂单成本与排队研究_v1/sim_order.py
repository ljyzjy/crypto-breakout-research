"""Tick-path hypothetical individual orders with explicit queue assumptions."""
from __future__ import annotations
import math
import numpy as np

M=60_000;DAY=86_400_000
END=1793491200000  # 2026-11-01T00:00:00Z

def make_plan(s,market,times,prices):
    submit=int(s.ts);i=int(np.searchsorted(times,submit,side='left'))-1
    if i<0 or times[i]<submit-30_000:return None,'reference_trade_unknown'
    ref=float(prices[i]);side=int(s.side);stop=float(s.stop_price);atr=float(s.atr)
    distance=side*(ref-stop)
    if side*(ref-float(s.signal_close))>.25*atr:return None,'reference_deviation'
    if distance<=0 or distance>1.5*atr or 2*distance/ref<.006:return None,'reference_stop_cost'
    prev=market.bar(s.contract,submit-M)
    if prev is None or not np.isfinite(prev[5]) or prev[5]<=0:return None,'prior_quote_unknown'
    size=min(250.,2.5/(distance/ref+.002),.001*float(prev[5]))
    if size<10:return None,'notional_below_minimum'
    q=size/ref
    return {'submit':submit,'activate':submit+1000,'expiry':min(submit+3*M,int(s.quarter_start)+15*M),
       'reference':ref,'planned_notional':size,'planned_qty':q,'side':side,'stop':stop,
       'atr':atr,'signal_close':float(s.signal_close),'contract':s.contract,
       'observation_id':s.observation_id},'ready'

def funding_cost(plan, fills, exit_ts, market):
    first=min(t for t,q in fills);total=0.;c=plan['contract'];side=plan['side']
    for minute in range((first//M)*M,(exit_ts//M)*M+1,M):
        if market.bar(c,minute,True) is None or not market.funding_ok(c,minute):
            return None
        for ft,rate in market.funding.get(c,{}).get(minute,[]):
            if not first<=ft<=exit_ts:continue
            mark=float(market.bar(c,minute,True)[0])
            before=sum(q for t,q in fills if t<ft)
            equal=sum(q for t,q in fills if t==ft)
            debit=side*before*mark*rate
            if ft==exit_ts:debit=max(0.,debit)
            debit+=max(0.,side*equal*mark*rate)
            total+=debit
    return total

def run_order(plan,times,prices,quantities,buyer_maker,method,target_r,queue_multiple,market):
    side=plan['side'];stop=plan['stop'];ref=plan['reference'];qty_goal=plan['planned_qty']
    act=plan['activate'];expiry=plan['expiry'];limit=ref;start=int(np.searchsorted(times,act,side='right'))
    result={'observation_id':plan['observation_id'],'method':method,'target_r':target_r,
            'queue_multiple':queue_multiple,'planned_notional':plan['planned_notional'],
            'planned_qty':qty_goal,'reference':ref,'submit_ts':plan['submit'],'expiry_ts':expiry}
    if start>=len(times):return dict(result,status='future_tape_unknown')
    qty_at_limit=0.;qty_through=0.;through_stop_same_tick=False
    if method=='market':
        t=int(times[start]);raw=float(prices[start]);entry=raw*(1+side*.0005)
        distance=side*(entry-stop)
        if t>=int(plan['expiry']) and t>=int(plan['submit']//(15*M)*(15*M)+15*M):
            return dict(result,status='not_submitted_after_quarter')
        if side*(entry-plan['signal_close'])>.25*plan['atr']:
            return dict(result,status='not_submitted_entry_deviation')
        if distance<=0 or distance>1.5*plan['atr'] or 2*distance/entry<.006:
            return dict(result,status='not_submitted_stop_cost')
        fills=[(t,qty_goal)];qty=qty_goal;entry_fee_rate=.0005
        target=entry+side*target_r*distance;next_i=start+1;pending=False
    else:
        t=None;entry=limit;distance=side*(entry-stop);target=entry+side*target_r*distance
        fills=[];qty=0.;entry_fee_rate=.0002;next_i=start;pending=True
    queue=queue_multiple*qty_goal;exit_ts=None;exit_raw=None;reason=None;last_i=None
    first_fill=fills[0][0] if fills else None
    for j in range(next_i,len(times)):
        tt=int(times[j]);p=float(prices[j]);vol=float(quantities[j]);last_i=j
        if tt>=END:break
        if pending and tt>=expiry:pending=False
        if qty>0:
            first_fill=fills[0][0]
            localday=(first_fill+8*HOUR)//DAY
            close_ts=localday*DAY+23*HOUR+55*M-8*HOUR
            deadline=min(first_fill+60*M,close_ts,END)
            if tt>=deadline:
                exit_ts=tt;exit_raw=p;reason='time_or_day';break
        # A price print beyond the limit implies assumed traversal of the
        # resting level. Fill remaining before the same-print protective stop.
        if pending:
            crosses=side*(p-limit)<-max(1e-12,abs(limit)*1e-10)
            at_limit=abs(p-limit)<=max(1e-12,abs(limit)*1e-10)
            opposite=bool(buyer_maker[j]) if side==1 else not bool(buyer_maker[j])
            if crosses:
                take=qty_goal-qty
                if take>0:
                    fills.append((tt,take));qty+=take;qty_through+=take
                    if side*(p-stop)<=0:through_stop_same_tick=True
                queue=0.;pending=False
            elif at_limit and opposite:
                available=max(0.,vol-queue);queue=max(0.,queue-vol)
                take=min(qty_goal-qty,available)
                if take>0:fills.append((tt,take));qty+=take;qty_at_limit+=take
                if qty>=qty_goal*(1-1e-12):pending=False
        if qty>0:
            stop_hit=side*(p-stop)<=0;target_hit=side*(p-target)>=0
            if stop_hit or target_hit:
                exit_ts=tt;exit_raw=p;reason='stop' if stop_hit else 'target';pending=False;break
        if not pending and qty<=0:
            return dict(result,status='unfilled_expired',filled_qty=0.,fill_fraction=0.,net=0.)
    if qty<=0:return dict(result,status='unfilled_expired',filled_qty=0.,fill_fraction=0.,net=0.)
    if exit_ts is None:
        deadline=min(fills[0][0]+60*M,((fills[0][0]+8*HOUR)//DAY)*DAY+23*HOUR+55*M-8*HOUR,END)
        if deadline==END and last_i is not None and int(times[last_i])<END and END-int(times[last_i])<=30_000:
            exit_ts=int(times[last_i]);exit_raw=float(prices[last_i]);reason='period_end'
        else:return dict(result,status='exit_tape_unknown',filled_qty=float(qty),fill_fraction=float(qty/qty_goal))
    fund=funding_cost(plan,fills,exit_ts,market)
    if fund is None:return dict(result,status='funding_or_mark_unknown',filled_qty=float(qty),fill_fraction=float(qty/qty_goal))
    exit_fill=exit_raw*(1-side*.0005)
    gross=side*qty*(exit_fill-entry);entry_fee=qty*entry*entry_fee_rate;exit_fee=qty*exit_fill*.0005
    net=gross-entry_fee-exit_fee-fund
    return dict(result,status='filled',filled_qty=float(qty),fill_fraction=float(min(1.,qty/qty_goal)),
       first_fill_ts=int(fills[0][0]),last_fill_ts=int(fills[-1][0]),number_of_fill_events=len(fills),
       first_fill_fraction=float(fills[0][1]/qty_goal),
       qty_at_limit=float(qty_at_limit),qty_assumed_through=float(qty_through),
       assumed_through_stop_same_tick=through_stop_same_tick,
       entry_price=float(entry),target=float(target),exit_ts=int(exit_ts),exit_raw=float(exit_raw),
       exit_price=float(exit_fill),exit_reason=reason,gross_after_exit_slip=float(gross),
       entry_fee=float(entry_fee),exit_fee=float(exit_fee),funding_cost=float(fund),net=float(net),
       net_bp_per_planned_notional=float(net/plan['planned_notional']*10000))

HOUR=3_600_000
