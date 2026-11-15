"""Test prior completed minute's directional taker flow at first touch."""
import gc,hashlib,json,sys
from pathlib import Path
import pandas as pd
import numpy as np
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
flow.HERE=HERE;flow.eng=touch.engine
VARIANTS=[('preflow_aligned_1r',1.,False),('preflow_strong_1r',1.,True),
          ('preflow_aligned_2r',2.,False),('preflow_strong_2r',2.,True)]
def select(signals,name):
    hold=signals.side*(signals.raw_entry_5s-signals.level)>0
    threshold=.10 if '_strong_' in name else 0.
    return signals[hold&signals.preflow.ge(threshold)].copy()
flow.candidate=select
def load():
    tape=HERE.parent/'第十四轮_首分钟逐笔突破'
    meta=json.loads((tape/'首分钟逐笔校验档案.json').read_text(encoding='utf-8'))
    fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference',
           'no_price_before_candle_end','minute_archive_mismatch'}
    if meta['archive_errors'] or any(meta['statuses'].get(x,0) for x in fatal):raise ValueError('opening_tape_incomplete')
    d=pd.read_parquet(tape/'首分钟首次触价与五秒参考.parquet');d=d[d.status.eq('verified')].copy()
    d['tick_status']='verified'
    assert d.observation_id.is_unique and (d.entry_exec_ts>=d.decision_ts+5000).all()
    assert (d.feature_known_ts==d.quarter_start).all() and (d.entry_exec_ts<d.quarter_end).all()
    groups=[]
    for (year,contract),g in d.groupby(['source_year','contract']):
        root=HERE.parent.parent.parent
        norm=root/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
        assert raw.index.is_unique
        prev=raw.reindex(g.trigger_minute.to_numpy('int64')-60_000)
        total=prev.quote_volume.to_numpy(float);buy=prev.taker_buy_quote_volume.to_numpy(float)
        valid=np.isfinite(total)&np.isfinite(buy)&(total>0)&(buy>=0)&(buy<=total*(1+1e-8))
        imbalance=np.full(len(g),np.nan);imbalance[valid]=g.side.to_numpy()[valid]*(2*buy[valid]/total[valid]-1)
        group=g.copy();group['preflow']=imbalance;group['preflow_known_ts']=group.trigger_minute
        groups.append(group)
    out=pd.concat(groups,ignore_index=True);assert len(out)==len(d) and out.observation_id.is_unique
    out.to_parquet(HERE/'事前主动方向特征.parquet',index=False)
    return out
def read_trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    signals=load();training={};results=[]
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=signals[signals.source_year.eq(str(year))].copy()
        for name,target,active in VARIANTS:
            for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
                sm=flow.simulate(subset,name,start,end,market,guard,lev,scenario,period,target_override=target)
                results.append(sm)
                if lev==20 and scenario=='main':training[(year,name)]=sm
        del market,guard,subset;gc.collect()
    scores=[]
    for name,target,active in VARIANTS:
        a=training[(2024,name)];b=training[(2026,name)]
        comb=read_trades('train_h1_2024',name)+read_trades('train_may_jul_2026',name)
        pos=sum(t['net'] for t in comb if t['net']>0);neg=-sum(t['net'] for t in comb if t['net']<0)
        rate=100*sum(t['net']>0 for t in comb)/len(comb) if comb else None;pf=pos/neg if neg else None
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'strong_filter':active,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(comb),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'事前主动方向训练全部账户.json',results);flow.dump(HERE/'事前主动方向训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    decision={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
      'training_success':bool(passed),'metrics':chosen,
      'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
      'training_sha256':hashlib.sha256((HERE/'事前主动方向训练候选对照.json').read_bytes()).hexdigest(),
      'limit':'Prior-minute taker flow uses only completed candles; entry reference observation-to-order latency remains unmodeled.'}
    flow.dump(HERE/'事前主动方向冻结候选.json',decision)
    print('PREFLOW_TRAIN_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
