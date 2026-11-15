"""Locate opening-minute possible triggers using only pre-minute entry filters."""
import gc,json,sys
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(PARENT/'第二轮_成本空间与即时成交'))
import flow_research as flow
import train_and_compare as r2
f=flow.forward;M=60_000;Q=15*M
def generate(year,start,end):
    r2.configure(year);market=f.FixedMarket();guard=f.FixedGuard(market)
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    hi=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    rows=[];counts=Counter()
    for symbol,contract in guard.mapping.items():
        a=market.trade[contract];valid=f.valid_trade(a);feat=f.prior.calculate(a,valid)
        up=valid&np.isfinite(feat['upper'])&(a[:,1]>feat['upper'])
        dn=valid&np.isfinite(feat['lower'])&(a[:,2]<feat['lower'])
        indexes=np.flatnonzero((up|dn)&(np.arange(len(a))%15==0))
        last=-10**18
        for i in indexes:
            t=int(f.GRID[i])
            if t<lo or t>=hi:continue
            counts['possible_first_minute_events']+=1
            if t-last<60*M:counts['event_cooldown']+=1;continue
            last=t
            if ((t//M+480)%1440)>=1320:counts['late_day']+=1;continue
            atr=float(feat['atr'][i])
            if i<21*15 or not valid[i-21*15:i].all() or not np.isfinite(atr) or atr<=0:
                counts['missing_history_or_atr']+=1;continue
            previous=a[i-15:i];earlier=a[i-21*15:i-15].reshape(20,15,7)
            earlier_counts=earlier[:,:,6].sum(axis=1);previous_count=previous[:,6].sum()
            if not np.isfinite(earlier_counts).all() or not np.isfinite(previous_count) or earlier_counts.mean()<=0:
                counts['missing_trade_count']+=1;continue
            ratio=float(previous_count/earlier_counts.mean())
            body=float((previous[-1,3]-previous[0,0])/atr);directions={}
            for side,hit in [(1,bool(up[i])),(-1,bool(dn[i]))]:
                if not hit or not guard.eligible(symbol,side,t) or side*body<.1:continue
                level=float(feat['upper'][i] if side==1 else feat['lower'][i])
                stop=float(a[i-1,2]-.1*atr if side==1 else a[i-1,1]+.1*atr)
                distance=side*(level-stop)
                if distance<=0 or distance>1.5*atr or 2*distance/level<.006:continue
                rank=guard.rank(symbol,side,t)
                directions[str(side)]={'stop_price':stop,'level':level,'score':rank['score'],
                    'rank':rank['rank'],'rvol':rank['rvol'],'liquidity_rank':rank['liquidity_rank']}
            if not directions:counts['known_directional_filters']+=1;continue
            rows.append({'observation_id':f'opening|{symbol}|{t}','symbol':symbol,'contract':contract,
              'trigger_minute':t,'quarter_start':t,'quarter_end':t+Q,
              'upper':float(feat['upper'][i]),'lower':float(feat['lower'][i]),'atr':atr,
              'prior_prefix_ratio':ratio,'prior_body_atr':body,'possible_long':bool(up[i]),'possible_short':bool(dn[i]),
              'long_known_eligible':'1' in directions,'short_known_eligible':'-1' in directions,
              'long_spec':json.dumps(directions.get('1'),ensure_ascii=False),
              'short_spec':json.dumps(directions.get('-1'),ensure_ascii=False),
              'source_year':str(year),'day':pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d')})
        print('OPENING_CANDIDATES',year,symbol,len(rows),flush=True)
    out=pd.DataFrame(rows).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert out.observation_id.is_unique
    out.to_parquet(HERE/f'首分钟潜在候选_{year}.parquet',index=False)
    counts['potential_events']=len(out)
    flow.dump(HERE/f'首分钟生成统计_{year}.json',{'counts':dict(counts),
      'note':'Minute high/low only locate events for tape verification, and never set actual trigger direction or price.'})
    del market,guard;gc.collect();return len(out)
if __name__=='__main__':
    print('OPENING_COUNTS',generate(2024,'2024-01-01','2024-06-30'),
          generate(2026,'2026-05-01','2026-07-31'),flush=True)
