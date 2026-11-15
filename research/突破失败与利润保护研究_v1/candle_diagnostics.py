"""Describe the entered breakout bars; not a replay or implementable closing rule."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
NORM = HERE.parent.parent / 'work' / 'breakout_november_2026' / 'normalized'
M = 60_000
rows = []
for period in ['fixed_full', 'nov_new_12days']:
    trades = json.loads((HERE / f'{period}_base_2r_main_trades.json').read_text(encoding='utf-8'))
    for contract in sorted(set(t['contract'] for t in trades)):
        bars = pd.read_parquet(NORM / f'{contract}_klines.parquet', columns=['ts','open','close']).set_index('ts')
        assert bars.index.is_unique
        for t in (x for x in trades if x['contract'] == contract):
            side = 1 if t['side'] == 'long' else -1
            end = t['quarter_end_ts']
            assert t['entry_ts'] < end
            close = float(bars.at[end - M, 'close'])
            hypothetical_exit = close * (1 - side*.0005)
            hypothetical_exit_fee = t['qty'] * hypothetical_exit * .0005
            # The close is only a mark, not a trade: it is known at bar end.
            marked_net_without_funding = side*t['qty']*(hypothetical_exit-t['entry'])-t['entry_fee']-hypothetical_exit_fee
            rows.append({'period':period, 'observation_id':t['observation_id'], 'symbol':t['symbol'],
                'side':t['side'], 'entry_ts':t['entry_ts'], 'quarter_end_ts':end,
                'remaining_minutes_at_entry':(end-t['entry_ts'])/M, 'entry':t['entry'],
                'quarter_close':close, 'break_level':t['break_level'],
                'close_beyond_level':side*(close-t['break_level'])>0,
                'entry_to_close_price_positive':side*(close-t['entry'])>0,
                'close_marked_net_ex_funding':marked_net_without_funding,
                'close_marked_net_positive_ex_funding':marked_net_without_funding>0,
                'actual_exit_at_or_before_candle_close':t['exit_ts']<=end,
                'realized_trade_net':t['net']})
out = pd.DataFrame(rows)
out.to_csv(HERE / '突破柱收盘标记诊断.csv', index=False, encoding='utf-8-sig')
for period, g in out.groupby('period'):
    print(period, 'trades',len(g), 'beyond_level',int(g.close_beyond_level.sum()),
          'entry_to_close_price_positive',int(g.entry_to_close_price_positive.sum()),
          'marked_net_positive_ex_funding',int(g.close_marked_net_positive_ex_funding.sum()),
          'actual_exit_by_close',int(g.actual_exit_at_or_before_candle_close.sum()),
          'median_remaining_minutes',g.remaining_minutes_at_entry.median(),flush=True)
print('NOTE close marks are not executable results: ignore earlier exits, omit funding, and assume close price; no causal signal uses the completed candle.')
