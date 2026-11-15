"""Synthetic integration tests for single-retest and delayed entry composition."""
from pathlib import Path
import hashlib
import json
import pandas as pd

import 逐笔组合决策 as composed

H = Path(__file__).resolve().parent


def make(rows):
    rows = sorted(rows, key=lambda x: x[0])
    tape = pd.DataFrame({"agg_trade_id": range(len(rows)), "transact_time": [x[0] for x in rows],
                         "price": [x[1] for x in rows], "quantity": [1.] * len(rows),
                         "is_buyer_maker": [x[2] for x in rows]})
    minute = tape[tape.transact_time.lt(60_000)]
    bars = pd.DataFrame({"open": [float(minute.price.iloc[0])], "high": [float(minute.price.max())],
                         "low": [float(minute.price.min())], "close": [float(minute.price.iloc[-1])]}, index=[0])
    return tape, bars


def event():
    return {"trigger_minute": 0, "quarter_start": 0, "quarter_end": 900_000,
        "upper": 100., "lower": 98., "atr": 1., "long_known_eligible": True,
        "short_known_eligible": False, "long_spec": json.dumps({"level": 100., "stop_price": 99.5}),
        "short_spec": "null"}


def main():
    ticks = [(1000,100.1,'false'),(2000,100.05,'true'),(3000,100.05,'true'),(4000,100.05,'true'),
             (6000,99.95,'true'),(9000,99.9,'true'),(10000,100.1,'false'),(11000,100.1,'false'),
             (12000,100.1,'false'),(13000,100.1,'false'),(15000,100.2,'false'),(16000,100.21,'false'),
             (20000,100.25,'false'),(30000,102.,'false'),(35000,101.95,'true'),(100000,101.8,'true')]
    tape, bars = make(ticks)
    result = composed.decide(event(), tape, bars)
    assert result["origin"] == "retest" and result["first"]["status"] == "flow_filter_not_met"
    assert result["chosen"]["status"] == "qualified" and result["chosen"]["retest_ts"] == 10_000
    for lev in (10, 20):
        a = result["paths_5s"][f"normal_2r_{lev}x"]
        b = result["paths_1s"][f"one_second_2r_{lev}x"]
        assert a["status"] == b["status"] == "verified" and a["entry_ts"] == 20_000 and b["entry_ts"] == 16_000
        assert a["reason"] == b["reason"] == "target" and b["exit_ts"] >= b["exit_signal_ts"] + 5000
    changed = tape.copy();changed.loc[changed.transact_time == 100000, "price"] = 30.
    assert composed.decide(event(), changed, bars) == result
    wrong = bars.copy();wrong.loc[0, "open"] = 50.
    assert composed.decide(event(), tape, wrong)["chosen"]["status"] == "minute_trade_ohlc_mismatch"
    ineligible = event();ineligible["long_known_eligible"] = False
    assert composed.decide(ineligible, tape, bars)["chosen"]["status"] == "first_direction_ineligible"
    ticks2 = [(1000,100.1,'false'),(2000,100.1,'false'),(3000,100.1,'false'),(4000,100.1,'false'),
              (6000,100.2,'false'),(7000,99.4,'true'),(11000,100.22,'false'),
              (20000,102.,'false'),(25000,101.9,'true'),(100000,101.8,'true')]
    tape2, bars2 = make(ticks2)
    qualified = composed.decide(event(), tape2, bars2)
    assert qualified["origin"] == "original" and qualified["chosen"]["status"] == "qualified"
    for lev in (10,20):
        p = qualified["paths_1s"][f"one_second_2r_{lev}x"]
        assert p["status"] == "verified" and p["reason"] == "filled_beyond_risk_budget"
        assert p["entry_ts"] == 7000 and p["exit_ts"] >= 12_000
    path = H / "逐笔组合决策.py"
    out = {"all_checks_pass": True, "checks": ["single retest", "five/one-second entry",
        "future tick perturbation", "minute OHLC disagreement unknown", "ineligible direction",
        "one-second risk breach charged as filled"],
        "composition_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (H / "逐笔组合合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXT63_COMPOSITION_TEST", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
