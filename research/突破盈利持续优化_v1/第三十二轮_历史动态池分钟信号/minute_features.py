"""Candidate localization from minute bars; direction/execution need public tape."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
M=60_000;H=60*M;Q=15*M
def derive(a,grid,symbol,year,pool_days):
    assert len(a)==len(grid) and len(a)%60==0 and np.all(np.diff(grid)==M)
    valid=flow.forward.valid_trade(a);feat=flow.forward.prior.calculate(a,valid)
    hours=a.reshape(-1,60,7);hvalid=valid.reshape(-1,60).all(axis=1)
    hour=pd.DataFrame({'symbol':symbol,'year':year,'open_time':grid[::60],
                       'close':np.where(hvalid,hours[:,-1,3],np.nan),
                       'quote_volume':np.where(hvalid,hours[:,:,5].sum(axis=1),np.nan),'valid':hvalid})
    quarters=a.reshape(-1,15,7);qvalid=valid.reshape(-1,15).all(axis=1)
    qclose=pd.Series(np.where(qvalid,quarters[:,-1,3],np.nan))
    ema=qclose.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    trend=np.select([qclose.gt(ema)&ema.gt(ema.shift()),qclose.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
    up=valid&np.isfinite(feat['upper'])&(a[:,1]>feat['upper'])
    down=valid&np.isfinite(feat['lower'])&(a[:,2]<feat['lower'])
    possible=np.flatnonzero(up|down)
    first=possible[np.r_[True,np.diff(possible//15)!=0]] if len(possible) else []
    if year==2024:lo=int(pd.Timestamp('2024-01-01',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000)
    elif year==2026:lo=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2026-08-01',tz='UTC').timestamp()*1000)
    else:raise ValueError(year)
    counters={'raw_first_touch_minutes':0,'cooled_out':0,'outside_pool':0,'late_day':0,'missing_prior':0,
              'body_trend_stop_rejected':0,'pre_rank_candidates':0}
    rows=[];last_open=-10**18;last_later=-10**18
    def make(i,cohort,body,pace):
        t=int(grid[i]);atr=float(feat['atr'][i]);spec={};prevquarter=i//15-1
        if prevquarter<0:return
        for side,hit in ((1,bool(up[i])),(-1,bool(down[i]))):
            if not hit or trend[prevquarter]!=side or side*body<.1:continue
            level=float(feat['upper'][i] if side==1 else feat['lower'][i])
            stop=float(a[i-1,2]-.1*atr if side==1 else a[i-1,1]+.1*atr)
            distance=side*(level-stop)
            if distance<=0 or distance>1.5*atr or 2*distance/level<.006:continue
            spec[str(side)]={'stop_price':stop,'level':level}
        if not spec:counters['body_trend_stop_rejected']+=1;return
        day=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d');quarter=t//Q*Q
        rows.append({'observation_id':f'{cohort}|{symbol}|{t}','symbol':symbol,'contract':symbol,'source_year':str(year),
                     'day':day,'cohort':cohort,'trigger_minute':t,'quarter_start':quarter,'quarter_end':quarter+Q,
                     'upper':float(feat['upper'][i]),'lower':float(feat['lower'][i]),'atr':atr,
                     'prior_prefix_ratio':float(pace),'prior_body_atr':float(body),
                     'possible_long':bool(up[i]),'possible_short':bool(down[i]),
                     'long_pre_rank':('1' in spec),'short_pre_rank':('-1' in spec),
                     'long_spec':json.dumps(spec.get('1'),ensure_ascii=False),
                     'short_spec':json.dumps(spec.get('-1'),ensure_ascii=False)})
        counters['pre_rank_candidates']+=1
    for i in first:
        t=int(grid[i]);in_range=lo<=t<hi;is_open=i%15==0
        if in_range:counters['raw_first_touch_minutes']+=1
        # The older later-minute generator updates its cooldown before checking
        # period or whether this is an opening event. Preserve that behavior.
        later_allowed=t-last_later>=60*M
        if later_allowed:last_later=t
        if not in_range:continue
        if is_open:
            if t-last_open<60*M:counters['cooled_out']+=1;continue
            last_open=t
        elif not later_allowed:counters['cooled_out']+=1;continue
        day=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d')
        if day not in pool_days:counters['outside_pool']+=1;continue
        if ((t//M+480)%1440)>=1320:counters['late_day']+=1;continue
        atr=float(feat['atr'][i])
        if not np.isfinite(atr) or atr<=0:counters['missing_prior']+=1;continue
        if is_open:
            if i<21*15 or not valid[i-21*15:i].all():counters['missing_prior']+=1;continue
            previous=a[i-15:i];earlier=a[i-21*15:i-15].reshape(20,15,7)
            counts=earlier[:,:,6].sum(axis=1);previous_count=previous[:,6].sum()
            if not np.isfinite(counts).all() or not np.isfinite(previous_count) or counts.mean()<=0:
                counters['missing_prior']+=1;continue
            pace=float(previous_count/counts.mean());body=float((previous[-1,3]-previous[0,0])/atr)
            make(i,'opening',body,pace)
        else:
            if not feat['current_prefix_valid'][i-1]:counters['missing_prior']+=1;continue
            pace=float(feat['ratio'][i-1]);q=i//15*15
            if not np.isfinite(pace) or pace<1.5:counters['missing_prior']+=1;continue
            body=float((a[i-1,3]-a[q,0])/atr);make(i,'touch',body,pace)
    return hour,rows,counters
