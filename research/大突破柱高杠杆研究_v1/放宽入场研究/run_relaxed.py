"""Predeclared broadened entries; offline research using minute bars only."""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
research=load('relaxed_study_parent',PARENT/'run_leverage_study.py')
f=research.forward;M=60_000;Q=15*M
research.HERE=HERE
research.CURVES=research.WORK/'relaxed_leverage_curves';research.CURVES.mkdir(parents=True,exist_ok=True)

def create_signals(market,guard):
    records=[];counts=Counter()
    for symbol,contract in guard.mapping.items():
        a=market.trade[contract];valid=f.valid_trade(a);features=f.prior.calculate(a,valid)
        long=valid&features['current_prefix_valid']&(a[:,3]>features['upper'])
        short=valid&features['current_prefix_valid']&(a[:,3]<features['lower'])
        cross=np.flatnonzero(long|short)
        first=cross[np.r_[True,np.diff(cross//15)!=0]] if len(cross) else []
        last=-10**18
        for i in first:
            t0=int(f.GRID[i]);decision=t0+M;entry=decision+M
            if t0-last<60*M:counts['event_cooldown']+=1;continue
            last=t0
            if decision<f.START or decision>=f.END:continue
            counts['first_events']+=1
            quarter_start=t0//Q*Q;quarter_end=quarter_start+Q
            if entry>=quarter_end:counts['outside_quarter']+=1;continue
            side=1 if long[i] else -1
            if not guard.eligible(symbol,side,decision):counts['rank_trend']+=1;continue
            atr=float(features['atr'][i]);level=float(features['upper'][i] if side==1 else features['lower'][i])
            ratio=float(features['ratio'][i]);q=i//15*15;close=float(a[i,3])
            if not np.isfinite(atr) or atr<=0 or not np.isfinite(ratio):counts['missing_atr_or_pace']+=1;continue
            body=side*(close-float(a[q,0]))/atr
            if ratio<1.5 or body<.25:counts['own_activity_or_body']+=1;continue
            stop=float(a[i,2]-.1*atr if side==1 else a[i,1]+.1*atr)
            distance=side*(close-stop)
            if distance<=0 or distance>1.5*atr or 2*distance/close<.006:counts['stop_cost']+=1;continue
            rank=guard.rank(symbol,side,decision)
            r=f.signal_record(symbol,contract,side,t0,decision,close,atr,stop,level,rank,'relaxed')
            qi=(decision-f.WARM)//Q-1
            major=qi>=0 and all(guard.trend[s][qi]==side for s in ['BTCUSDT','ETHUSDT'])
            end=q+14
            assert valid[q:end+1].all()
            final_close=float(a[end,3]);final_body=side*(final_close-float(a[q,0]))/float(a[q,0])
            beyond=side*(final_close-level)>0
            r.update(own_trade_count_ratio=ratio,partial_body_atr=body,major_trend_pass=bool(major),
                     early6_pass=bool(entry-quarter_start<=6*M),large_1pct_label=bool(final_body>=.01 and beyond),
                     large_halfpct_label=bool(final_body>=.005 and beyond),completed_body_pct=100*final_body)
            records.append(r)
        print('RELAXED_FEATURES',symbol,'candidates',len(records),flush=True)
    out=pd.DataFrame(records).sort_values(['ts','symbol']).reset_index(drop=True)
    assert len(out) and out.observation_id.is_unique and (out.ts==out.decision_ts+M).all()
    out.to_parquet(HERE/'放宽候选与事后标签.parquet',index=False)
    out.to_csv(HERE/'放宽候选与事后标签.csv',index=False,encoding='utf-8-sig')
    counts['eligible']=len(out);counts['major_trend_eligible']=int(out.major_trend_pass.sum())
    counts['early6_eligible']=int(out.early6_pass.sum())
    research.dump(HERE/'信号生成统计.json',{'counts':dict(counts),'time_scope':'5月1日至11月12日 UTC','lookahead_labels_not_inputs':True})
    return out

def main():
    market=f.FixedMarket();guard=f.FixedGuard(market)
    sig=create_signals(market,guard)
    universe=json.loads((PARENT/'全池大突破柱总数.json').read_text(encoding='utf-8'))
    variants=[('wide_2r',sig),('wide_3r',sig),('major_trend_3r',sig[sig.major_trend_pass].copy()),
              ('early6_3r',sig[sig.early6_pass].copy())]
    scenarios=[('main',.0005,.0005,0,0.),('stress',.001,.001,0,.002),('delay1',.0005,.0005,1,0.)]
    results=[]
    for period,start,end in research.PERIODS:
      for variant,signals in variants:
       for lev in (10,20):
        for scenario in scenarios:
            results.append(research.run_one(period,start,end,variant,signals,market,guard,lev,scenario,universe))
    research.dump(HERE/'全部账户结果.json',results)
    cols=['period','run_id','position_leverage','scenario','signal_candidates','trades','winning_trade_count','net_win_rate_pct',
          'net_pnl','return_pct','max_drawdown','intrabar_stress_dd','profit_factor','active_calendar_days',
          'in_original_quarter','large_1pct_caught','large_1pct_trade_win','large_halfpct_caught','large_1pct_universe',
          'average_entry_notional','average_isolated_margin','liquidation_proxy_count','planned_loss_exceeded_count',
          'valid_for_comparison','acceptance_pass','issues']
    pd.DataFrame(results).reindex(columns=cols).to_csv(HERE/'放宽入场完整对照.csv',index=False,encoding='utf-8-sig')
    print('RELAXED_STUDY_COMPLETE',len(results),flush=True)

if __name__=='__main__':main()
