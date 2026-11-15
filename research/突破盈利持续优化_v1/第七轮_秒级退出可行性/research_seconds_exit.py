"""Exploratory per-notional 15/30/60s exits using verified public aggTrades."""
import concurrent.futures
import hashlib
import io
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=HERE.parent.parent.parent
TOUCH=PARENT/'第六轮_柱内首次触价'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(PARENT/'第二轮_成本空间与即时成交'))
import flow_research as flow
import train_and_compare as r2

M=60_000;DAY=86_400_000;local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    contract,day,events=spec;name=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    err='unknown'
    for attempt in range(3):
      try:
        h=session().get(url+'.CHECKSUM',timeout=(12,45));h.raise_for_status();sha=h.text.strip().split()[0].lower()
        response=session().get(url,timeout=(12,120));response.raise_for_status();body=response.content
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        frames={e['observation_id']:[] for e in events}
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
            times=chunk.transact_time.to_numpy(np.int64)
            for e in events:
                t=int(e['trigger_minute']);part=chunk.loc[(times>=t)&(times<t+3*M)]
                if len(part):frames[e['observation_id']].append(part)
        rows=[]
        for e in events:
            parts=frames[e['observation_id']];out={**e,'archive_sha256':sha}
            if not parts:rows.append({**out,'status':'no_trigger_data'});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort').reset_index(drop=True)
            t=int(e['trigger_minute']);first=ticks[ticks.transact_time.lt(t+M)]
            crossing=first[(first.price>e['upper'])|(first.price<e['lower'])]
            if crossing.empty:rows.append({**out,'status':'ohlc_trade_mismatch'});continue
            cross=crossing.iloc[0];side=1 if float(cross.price)>e['upper'] else -1;decision=int(cross.transact_time)
            if not e['long_known_eligible' if side==1 else 'short_known_eligible']:
                rows.append({**out,'status':'first_direction_ineligible'});continue
            if decision+5000>=int(e['quarter_end']):rows.append({**out,'status':'expired_before_arrival'});continue
            entries=ticks.index[ticks.transact_time.ge(decision+5000)]
            if not len(entries):rows.append({**out,'status':'no_entry_reference'});continue
            entry_idx=int(entries[0]);entry=ticks.iloc[entry_idx];entry_ts=int(entry.transact_time)
            if entry_ts>=int(e['quarter_end']):rows.append({**out,'status':'no_price_before_candle_end'});continue
            side_spec=json.loads(e['long_spec'] if side==1 else e['short_spec']);stop=float(side_spec['stop_price'])
            raw=float(entry.price);fill=raw*(1+side*.0005);risk=side*(fill-stop)
            signal_distance=side*(float(cross.price)-stop);stopfrac=risk/fill
            if (side*(fill-float(cross.price))>.25*float(e['atr']) or risk<=0 or risk>1.5*float(e['atr']) or
                2*stopfrac<.006 or 2*signal_distance/float(cross.price)<.006 or
                stopfrac+.002+.0005+.0005>=.5*(1/20-.005-.005)):
                rows.append({**out,'status':'entry_risk_or_cost_rejected'});continue
            target=fill+side*risk;later=ticks.iloc[entry_idx+1:]
            out.update(side=side,decision_ts=decision,trigger_price=float(cross.price),entry_ts=entry_ts,
                       entry_raw=raw,entry_fill=fill,stop_price=stop,target=target,rank=side_spec['rank'])
            incomplete=False
            for seconds in (15,30,60):
                deadline=entry_ts+seconds*1000
                pre=later[later.transact_time.le(deadline)]
                hits=pre[((pre.price<=stop) if side==1 else (pre.price>=stop)) |
                         ((pre.price>=target) if side==1 else (pre.price<=target))]
                if len(hits):
                    hit=hits.iloc[0];signal_time=int(hit.transact_time)
                    stophit=float(hit.price)<=stop if side==1 else float(hit.price)>=stop
                    reason='stop' if stophit else 'target'
                else:signal_time=deadline;reason='time'
                exits=later[later.transact_time.ge(signal_time+5000)]
                if exits.empty:incomplete=True;break
                exitrow=exits.iloc[0]
                out.update({f'h{seconds}_exit_signal_ts':signal_time,f'h{seconds}_exit_reason':reason,
                            f'h{seconds}_exit_ts':int(exitrow.transact_time),f'h{seconds}_exit_raw':float(exitrow.price)})
            rows.append({**out,'status':'no_exit_reference' if incomplete else 'verified'})
        return {'contract':contract,'day':day,'status':'verified','sha256':sha,'bytes':len(body),'rows':rows}
      except Exception as exc:
        err=type(exc).__name__
        if attempt<2:time.sleep(1+attempt)
    return {'contract':contract,'day':day,'status':'error','error':err,
            'rows':[{**e,'status':'archive_error'} for e in events]}
def main():
    events=pd.read_parquet(TOUCH/'潜在触价候选_2026.parquet').copy()
    # Avoid crossing UTC files; this clock-only exclusion is known before the trigger.
    near=events.trigger_minute.mod(DAY).ge(DAY-3*M)
    excluded=int(near.sum());events=events[~near].copy()
    events['day']=pd.to_datetime(events.trigger_minute,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    tasks=[(c,day,g.to_dict('records')) for (c,day),g in events.groupby(['contract','day'])]
    reports=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for future in concurrent.futures.as_completed(futures):
            reports.append(future.result())
            if len(reports)%10==0:print('SECONDS_EXIT_ARCHIVES',len(reports),'/',len(tasks),flush=True)
    rows=[x for report in reports for x in report.pop('rows')]
    d=pd.DataFrame(rows);assert len(d)==len(events)
    r2.configure(2026);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    norm=flow.forward.NORM
    for contract,group in d[d.status.eq('verified')].groupby('contract'):
        f=pd.read_parquet(norm/f'{contract}_fundingRate.parquet')
        mark=pd.read_parquet(norm/f'{contract}_markPriceKlines.parquet',columns=['ts','open','high','low']).set_index('ts')
        for idx,row in group.iterrows():
            side=int(row.side);entry=float(row.entry_fill);qty=1./entry
            if not guard.eligible(row.symbol,side,int(row.entry_ts)//M*M):
                d.loc[idx,'status']='rank_trend_changed';continue
            for seconds in (15,30,60):
                exit_ts=int(row[f'h{seconds}_exit_ts']);exit_fill=float(row[f'h{seconds}_exit_raw'])*(1-side*.0005)
                eligible_funding=f[(f.ts>=int(row.entry_ts))&(f.ts<=exit_ts)]
                charge=0.
                for x in eligible_funding.itertuples(index=False):
                    mt=int(x.ts)//M*M
                    if mt not in mark.index:d.loc[idx,'status']='missing_funding_mark';continue
                    signed=side*qty*float(mark.at[mt,'open'])*float(x.last_funding_rate)
                    charge+=max(0.,signed) if int(x.ts) in (int(row.entry_ts),exit_ts) else signed
                net=side*qty*(exit_fill-entry)-.0005-qty*exit_fill*.0005-charge
                d.loc[idx,f'h{seconds}_net_per_notional']=net
                d.loc[idx,f'h{seconds}_funding_per_notional']=charge
                proxy=False
                for minute in range(int(row.entry_ts)//M*M,exit_ts//M*M+M,M):
                    if minute not in mark.index:
                        d.loc[idx,'status']='missing_mark_price';continue
                    adverse=float(mark.at[minute,'low' if side==1 else 'high'])
                    balance=1/20-.0005+side*qty*(adverse-entry)-max(charge,0.)
                    proxy |= balance<=qty*adverse*(.005+.005)
                d.loc[idx,f'h{seconds}_liquidation_proxy']=bool(proxy)
    d.to_parquet(HERE/'秒级退出逐机会_2026训练.parquet',index=False)
    fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_entry_reference','no_price_before_candle_end',
           'no_exit_reference','missing_funding_mark','missing_mark_price'}
    status=d.status.value_counts().to_dict();risk=0;summaries=[]
    valid=d[d.status.eq('verified')]
    for seconds in (15,30,60):
        v=valid[f'h{seconds}_net_per_notional'].to_numpy(float)
        liq=int(valid[f'h{seconds}_liquidation_proxy'].fillna(False).sum());risk+=liq
        win=int((v>0).sum());pos=float(v[v>0].sum());neg=float(-v[v<0].sum())
        summaries.append({'holding_seconds':seconds,'trades':len(v),'net_win_rate_pct':100*win/len(v) if len(v) else None,
            'sum_net_per_unit_notional':float(v.sum()),'mean_net_pct':100*float(v.mean()) if len(v) else None,
            'profit_factor':pos/neg if neg else None,'liquidation_proxy_events':liq})
    passable=[x for x in summaries if x['trades']>=30 and x['net_win_rate_pct']>=60 and x['sum_net_per_unit_notional']>0 and x['profit_factor'] is not None and x['profit_factor']>1]
    complete=not any(status.get(x,0) for x in fatal) and risk==0
    selected=max(passable,key=lambda x:x['sum_net_per_unit_notional']) if passable and complete else None
    meta={'candidate_events':len(events),'clock_only_exclusions':excluded,'archives':len(tasks),
          'verified_archives':sum(x['status']=='verified' for x in reports),'status_counts':status,
          'complete_for_unit_comparison':complete,'strategies':summaries,'selected_for_further_account_test':selected,
          'note':'Independent per-notional paths, not shared-account results; 5s entry/exit observation assumptions and fixed slippage.',
          'archive_details':reports}
    (HERE/'秒级退出探索结果.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SECONDS_EXIT_COMPLETE',json.dumps({k:meta[k] for k in ['candidate_events','clock_only_exclusions','status_counts','complete_for_unit_comparison','strategies','selected_for_further_account_test']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
