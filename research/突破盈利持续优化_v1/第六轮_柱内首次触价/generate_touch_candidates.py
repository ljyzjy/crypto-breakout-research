"""Generate possible first-touch minutes using only pre-minute filters."""
import gc
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROUND2=PARENT/'第二轮_成本空间与即时成交'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND2))
import flow_research as flow
import train_and_compare as r2

f=flow.forward;M=60_000;Q=15*M
def generate(year,start,end,tag=None):
    r2.configure(year);market=f.FixedMarket();guard=f.FixedGuard(market)
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    hi=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    rows=[];counts=Counter()
    for symbol,contract in guard.mapping.items():
        a=market.trade[contract];valid=f.valid_trade(a);feature=f.prior.calculate(a,valid)
        up=valid&np.isfinite(feature['upper'])&(a[:,1]>feature['upper'])
        dn=valid&np.isfinite(feature['lower'])&(a[:,2]<feature['lower'])
        possible=np.flatnonzero(up|dn)
        first=possible[np.r_[True,np.diff(possible//15)!=0]] if len(possible) else []
        last=-10**18
        for i in first:
            t=int(f.GRID[i]);q=i//15*15
            if t-last<60*M:counts['event_cooldown']+=1;continue
            last=t
            if t<lo or t>=hi:continue
            counts['first_touch_minutes']+=1
            if i==q:counts['no_completed_prefix']+=1;continue
            if ((t//M+480)%1440)>=1320:counts['late_day']+=1;continue
            if not feature['current_prefix_valid'][i-1]:counts['bad_prefix']+=1;continue
            atr=float(feature['atr'][i]);pace=float(feature['ratio'][i-1])
            if not np.isfinite(atr) or atr<=0 or not np.isfinite(pace) or pace<1.5:
                counts['prior_pace_or_atr']+=1;continue
            quarter_start=t//Q*Q;prior_close=float(a[i-1,3]);qopen=float(a[q,0])
            body=(prior_close-qopen)/atr
            candidates={}
            for side,hit in [(1,bool(up[i])),(-1,bool(dn[i]))]:
                if not hit:continue
                if not guard.eligible(symbol,side,t) or side*body<.1:continue
                level=float(feature['upper'][i] if side==1 else feature['lower'][i])
                stop=float(a[i-1,2]-.1*atr if side==1 else a[i-1,1]+.1*atr)
                distance=side*(level-stop)
                if distance<=0 or distance>1.5*atr or 2*distance/level<.006:continue
                rank=guard.rank(symbol,side,t)
                candidates[str(side)]={'stop_price':stop,'level':level,'score':rank['score'],
                    'rank':rank['rank'],'rvol':rank['rvol'],'liquidity_rank':rank['liquidity_rank']}
            if not candidates:counts['known_directional_filters']+=1;continue
            rows.append({'observation_id':f'touch|{symbol}|{t}','symbol':symbol,'contract':contract,
              'trigger_minute':t,'quarter_start':quarter_start,'quarter_end':quarter_start+Q,
              'upper':float(feature['upper'][i]),'lower':float(feature['lower'][i]),'atr':atr,
              'prior_prefix_ratio':pace,'prior_body_atr':body,'possible_long':bool(up[i]),'possible_short':bool(dn[i]),
              'long_known_eligible':'1' in candidates,'short_known_eligible':'-1' in candidates,
              'long_spec':json.dumps(candidates.get('1'),ensure_ascii=False),
              'short_spec':json.dumps(candidates.get('-1'),ensure_ascii=False)})
        print('TOUCH_CANDIDATES',year,symbol,len(rows),flush=True)
    out=pd.DataFrame(rows).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert out.observation_id.is_unique
    tag=tag or str(year)
    out.to_parquet(HERE/f'潜在触价候选_{tag}.parquet',index=False)
    counts['potential_events']=len(out)
    flow.dump(HERE/f'潜在触价统计_{tag}.json',{'counts':dict(counts),
       'note':'OHLC identifies possible event minutes only; the first direction and 5s price must come from public aggTrades.'})
    del market,guard;gc.collect()
    return len(out)
def main():
    print('POTENTIAL_COUNTS',generate(2024,'2024-01-01','2024-06-30'),
          generate(2026,'2026-05-01','2026-07-31'),flush=True)
if __name__=='__main__':main()
