"""Independent strict-window first-second assessment for a source-reconciled case."""
from decimal import Decimal

D = Decimal


def first_second(agg, raw, start, upper, lower, long_eligible, short_eligible):
    stop = start + 60000
    def crossing(rows):
        return next((r for r in rows if start <= r[0] < stop and (r[2] > upper or r[2] < lower)), None)
    a, b = crossing(agg), crossing(raw)
    if a is None or b is None or (a[0], a[2]) != (b[0], b[2]):
        return {'status': 'unknown_first_cross'}
    ts, px = a[0], a[2]
    side = 1 if px > upper else -1
    eligible = long_eligible if side == 1 else short_eligible
    if not eligible:
        return {'status': 'known_no_order_direction', 'cross_ts': ts, 'side': side}
    def reference(rows):
        return next((r for r in rows if r[0] >= ts + 1000), None)
    ar, rr = reference(agg), reference(raw)
    if ar is None or rr is None or (ar[0], ar[2]) != (rr[0], rr[2]):
        return {'status': 'unknown_reference'}
    def flow(rows):
        w = [r for r in rows if ts < r[0] < ts + 1000]
        buy = sum((r[2] * r[3] for r in w if r[4] == 'false'), D(0))
        sell = sum((r[2] * r[3] for r in w if r[4] == 'true'), D(0))
        return len(w), buy, sell
    ac, ab, ass = flow(agg)
    rc, rb, rs = flow(raw)
    # Same exchange, same interval: exact trade-price x quantity totals required.
    if (ab, ass) != (rb, rs):
        return {'status': 'unknown_flow', 'cross_ts': ts, 'side': side}
    imbalance = D(side) * (ab - ass) / (ab + ass) if ab + ass else None
    outside = D(side) * (ar[2] - (upper if side == 1 else lower)) > 0
    reject = ac < 3 or imbalance is None or imbalance < D('.10') or not outside
    return {'status': 'known_no_order_flow' if reject else 'qualified_requires_path',
            'cross_ts': ts, 'cross_price': str(px), 'side': side,
            'reference_ts': ar[0], 'reference_price': str(ar[2]), 'reference_outside': outside,
            'aggregate_count': ac, 'raw_count': rc, 'buy': str(ab), 'sell': str(ass),
            'imbalance': None if imbalance is None else str(imbalance)}
