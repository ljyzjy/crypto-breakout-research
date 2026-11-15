"""Synthetic check: features do not use unclosed hours and require 20 valid lags."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from prepare_hourly import indicators,H
HERE=Path(__file__).resolve().parent
lo=int(pd.Timestamp('2026-04-01',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2026-05-02',tz='UTC').timestamp()*1000)
t=np.arange(lo,hi,H,dtype=np.int64);i=np.arange(len(t));close=100*np.exp(.0002*i+.001*np.sin(i/7))
quote=np.full(len(t),100.);decision=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
quote[np.where(t==decision-H)[0][0]]=200.
g=pd.DataFrame({'symbol':'XUSDT','open_time':t,'close':close,'quote_volume':quote,'valid':True})
x=indicators(g,'2026-04-01','2026-05-02');before=x.set_index('decision_hour').loc[decision]
assert np.isfinite(before.score) and np.isclose(before.rvol,2.)
future=g.copy();future.loc[future.open_time>=decision,'close']*=10;future.loc[future.open_time>=decision,'quote_volume']*=100
after=indicators(future,'2026-04-01','2026-05-02').set_index('decision_hour').loc[decision]
assert np.isclose(before.score,after.score) and np.isclose(before.rvol,after.rvol)
missing=g.copy();missing.loc[missing.open_time.eq(decision-H-10*24*H),'valid']=False
z=indicators(missing,'2026-04-01','2026-05-02').set_index('decision_hour').loc[decision]
assert np.isnan(z.rvol)
out={'closed_hour_only':True,'future_hour_perturbation_no_effect':True,'twenty_same_hour_lags_required':True,
     'not_yet_minute_verified':True}
(HERE/'小时特征时序合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE31_SYNTHETIC_PASS',json.dumps(out),flush=True)
