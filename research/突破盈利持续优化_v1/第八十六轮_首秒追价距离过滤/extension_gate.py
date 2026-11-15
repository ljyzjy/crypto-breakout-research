"""Strict causal one-second extension gate with one fixed cost-scale threshold."""
from decimal import Decimal, InvalidOperation

D = Decimal


def gate(event):
    try:
        side = int(event['side'])
        ref, level = D(str(event['raw_entry_1s'])), D(str(event['level']))
        decision, observed = int(event['decision_ts']), int(event['entry_exec_ts'])
        if side not in (-1, 1) or not ref.is_finite() or not level.is_finite() or ref <= 0 or level <= 0 or observed < decision + 1000:
            return None, None
        distance = D(side) * (ref - level) / level
        return D(0) < distance <= D('.0005'), distance
    except (KeyError, TypeError, ValueError, InvalidOperation, ZeroDivisionError):
        return None, None
