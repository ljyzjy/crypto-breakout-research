"""Frozen completed-week, two-market SMA29 gate; no current-week bars."""
from decimal import Decimal, localcontext

W, MON = 604800000, 345600000


def last_completed_week(decision_ts):
    return ((int(decision_ts) - MON) // W) * W + MON - W


def gate(event, week_map):
    decision, side = int(event['decision_ts']), int(event['side'])
    if side not in (-1, 1):
        raise ValueError('invalid side')
    last = last_completed_week(decision)
    assert last + W <= decision < last + 2 * W
    result = {'week_gate': None, 'last_week_start': last}
    flags = []
    with localcontext() as ctx:
        ctx.prec = 50
        for symbol in ('BTCUSDT', 'ETHUSDT'):
            closes = []
            for i in range(29):
                start = last - i * W
                row = week_map.get((symbol, start))
                if not row or row.get('status') != 'verified' or row.get('week_end_exclusive') != start + W or start + W > decision:
                    return result
                close = Decimal(str(row['official_ohlc']['close']))
                if not close.is_finite() or close <= 0:
                    return result
                closes.append(close)
            mean = sum(closes) / Decimal(29)
            result[symbol + '_close'] = closes[0]
            result[symbol + '_sma29'] = mean
            flags.append(Decimal(side) * (closes[0] - mean) > 0)
    result['week_gate'] = all(flags)
    return result
