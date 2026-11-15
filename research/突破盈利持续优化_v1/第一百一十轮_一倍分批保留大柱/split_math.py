"""Unit-notional PnL for two independently settled equal-size exit legs."""
from decimal import Decimal as D


def leg_net(path, exit_slip):
    side = D(int(path["side"]))
    entry, raw = D(str(path["entry_fill"])), D(str(path["exit_raw"]))
    funding = D(str(path["funding"]))
    assert side in (D(-1), D(1)) and entry > 0 and raw > 0 and funding.is_finite()
    exit_ = raw * (1 - side * exit_slip)
    return side * (exit_ - entry) / entry - D(".0005") - D(".0005") * exit_ / entry - funding


def half_and_half(one_r, two_r, exit_slip):
    assert int(one_r["entry_ts"]) == int(two_r["entry_ts"]) and int(one_r["side"]) == int(two_r["side"])
    assert abs(D(str(one_r["entry_fill"])) - D(str(two_r["entry_fill"]))) < D("1e-9")
    return (leg_net(one_r, exit_slip) + leg_net(two_r, exit_slip)) / D(2)
