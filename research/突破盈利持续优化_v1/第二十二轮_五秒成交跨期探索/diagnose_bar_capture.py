"""Describe ex-post large-candle coverage for the already frozen signal."""
import json
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
raw=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
rows=[]
for year,folder,period,name in [
    ('2024',HERE,'cross_2024','cross_partial_2r'),
    ('2026',PARENT/'第二十一轮_五秒成交与分批保护','screen_2026','combined_partial_2r')]:
    source=HERE/'五秒主动成交特征_2024.parquet' if year=='2024' else PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet'
    feat=pd.read_parquet(source).rename(columns={'status':'flow_status','count':'flow_count','directional_imbalance':'flow_imbalance'})
    data=raw[raw.status.eq('verified')&raw.source_year.eq(year)].merge(feat,on='observation_id',validate='one_to_one')
    selected=(data.flow_status.eq('verified')&data.flow_count.ge(3)&data.flow_imbalance.ge(.1)&
              (data.side*(data.raw_entry_5s-data.level)>0))
    large=data.large_1pct_label.astype(bool)
    sm=json.loads((folder/f'{period}_{name}_20x_main_summary.json').read_text(encoding='utf-8'))
    trades=json.loads((folder/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
    labels=data.set_index('observation_id').large_1pct_label.astype(bool)
    large_trades=[t for t in trades if bool(labels.loc[t['observation_id']]) and t['entry_ts']<t['quarter_end_ts']]
    other_trades=[t for t in trades if t not in large_trades]
    assert len(large_trades)==sm['large_1pct_caught'] and len(large_trades)+len(other_trades)==len(trades)
    out={'period':year,'candidate_first_touch_events':len(data),'candidate_large_bars':int(large.sum()),
         'selected_signal_events':int(selected.sum()),'selected_that_became_large_bars':int((selected&large).sum()),
         'signal_precision_pct':100*float((selected&large).sum())/int(selected.sum()) if selected.any() else None,
         'cohort_recall_pct':100*float((selected&large).sum())/int(large.sum()) if large.any() else None,
         'account_trades_entered_before_large_bar_close':sm['large_1pct_caught'],
         'large_bar_trade_wins':sum(t['net']>0 for t in large_trades),
         'large_bar_trade_net':sum(t['net'] for t in large_trades),
         'other_trade_count':len(other_trades),'other_trade_net':sum(t['net'] for t in other_trades),
         'account_trades_total':sm['trades'],
         'note':'Labels use 15m closing information only for this diagnostic; candidate-cohort recall is not market-wide recall and no captured price return is implied.'}
    rows.append(out)
(HERE/'大突破柱事后机会诊断.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
pd.DataFrame(rows).to_csv(HERE/'大突破柱事后机会诊断.csv',index=False,encoding='utf-8-sig')
print('BAR_CAPTURE_DIAGNOSTIC',json.dumps(rows,ensure_ascii=False),flush=True)
