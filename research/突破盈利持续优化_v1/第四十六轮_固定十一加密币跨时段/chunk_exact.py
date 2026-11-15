"""Recompute minute features in small chunks while preserving global EMA state."""
import shutil,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import minute_features_chunked as m
ROOT=Path(__file__).resolve().parent.parent.parent.parent
def derive_chunked(a,grid,symbol,year,pool_days):
    assert len(a)==len(grid) and len(a)%1440==0
    valid=m.flow.forward.valid_trade(a);quarters=a.reshape(-1,15,7);qvalid=valid.reshape(-1,15).all(axis=1)
    qclose=pd.Series(np.where(qvalid,quarters[:,-1,3],np.nan))
    ema=qclose.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    trend=np.select([qclose.gt(ema)&ema.gt(ema.shift()),qclose.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
    parts=[];events=[];block=7*1440;warm=1440
    for begin in range(0,len(grid),block):
        while psutil.virtual_memory().available<300*1024**2:
            if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
            time.sleep(3)
        if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
        left=max(0,begin-warm);end=min(len(grid),begin+block)
        assert left%1440==0 and end%1440==0
        hours,rows,_=m.derive(a[left:end],grid[left:end],symbol,year,pool_days,trend[left//15:end//15])
        lo=int(grid[begin]);hi=int(grid[end-1])+60_000
        parts.append(hours[hours.open_time.ge(lo)&hours.open_time.lt(hi)])
        events.extend(x for x in rows if lo<=int(x['trigger_minute'])<hi)
    result=pd.concat(parts,ignore_index=True);assert len(result)==len(grid)//60 and result.open_time.is_unique
    return result,events,{'note':'Causal trend is calculated once globally; one prior day warms each seven-day feature block.'}
