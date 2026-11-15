"""Describe observed payouts, dependence, and paired trades; no parameter search."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
names=['baseline_2r','target_1r','target_1_5r','confirm_1r']
records={};summary=[]
dates=pd.date_range('2026-05-01','2026-10-31',freq='D').strftime('%Y-%m-%d')
rng=np.random.default_rng(20261114); n=len(dates);k=int(np.ceil(n/7))
samples=(rng.integers(0,n-6,size=(2000,k))[:,:,None]+np.arange(7)).reshape(2000,-1)[:,:n]
for name in names:
    trades=json.loads((HERE/f'full_{name}_main_trades.json').read_text(encoding='utf-8'))
    records[name]=trades
    df=pd.DataFrame(trades)
    if df.empty:continue
    winners=df[df.net>0].net;losses=-df[df.net<0].net
    df['day']=pd.to_datetime(df.entry_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    daily=df.assign(win=df.net.gt(0).astype(int)).groupby('day').agg(n=('net','size'),wins=('win','sum')).reindex(dates,fill_value=0)
    count=daily.n.to_numpy()[samples].sum(axis=1);wins=daily.wins.to_numpy()[samples].sum(axis=1)
    dist=np.divide(wins,count,out=np.full(len(count),np.nan),where=count>0)*100
    ci=np.nanquantile(dist,[.025,.975]);aw=float(winners.mean());al=float(losses.mean())
    summary.append({'variant':name,'trades':len(df),'wins':len(winners),'losses':len(losses),
      'mean_net_win_u':aw,'mean_net_loss_u':al,'sample_breakeven_win_pct':100*al/(al+aw),
      'win_rate_pct':100*len(winners)/len(df),'block_ci95_low_pct':float(ci[0]),
      'block_ci95_high_pct':float(ci[1]),'net_pnl_u':float(df.net.sum())})
a={x['observation_id']:x for x in records['baseline_2r']};b={x['observation_id']:x for x in records['target_1r']}
keys=a.keys()&b.keys()
pair={'same_signal_ids':len(keys),'only_2r':len(a.keys()-b.keys()),'only_1r':len(b.keys()-a.keys()),
      'same_entry_timestamp_count':sum(a[k]['entry_ts']==b[k]['entry_ts'] for k in keys),
      'same_entry_price_count':sum(abs(a[k]['entry']-b[k]['entry'])<1e-9 for k in keys),
      'count_1r_net_greater':sum(b[k]['net']>a[k]['net'] for k in keys),
      'count_2r_net_greater':sum(a[k]['net']>b[k]['net'] for k in keys),
      'sum_1r_minus_2r_u':sum(b[k]['net']-a[k]['net'] for k in keys)}
report={'summary':summary,'paired_2r_versus_1r':pair,
 'notes':'Observed mean-win/loss breakeven and descriptive 7-day block-bootstrap intervals are not forward forecasts; shared capital and exit timing can change quantities.'}
(HERE/'胜率与盈亏拆解.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
