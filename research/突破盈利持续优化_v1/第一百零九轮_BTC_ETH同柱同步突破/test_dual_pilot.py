import hashlib
import json
from pathlib import Path

from dual_pilot_engine import find_sync, simulate_path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    L = {"BTCUSDT": {"upper": "100", "lower": "90"}, "ETHUSDT": {"upper": "200", "lower": "180"}}
    events = [(10000, "BTCUSDT", 1, "100.2"), (10000, "ETHUSDT", 1, "200.2"),
              (11000, "BTCUSDT", 2, "100.3"), (11000, "ETHUSDT", 2, "200.3"),
              (11001, "BTCUSDT", 3, "100.4")]
    x = find_sync(events, L, 0, 30000)
    assert x["status"] == "confirmed" and x["side"] == 1 and x["signal_ts"] == 10001 and x["reference_ts"] == 11001
    y = find_sync([(0, "BTCUSDT", 1, 101), (3001, "ETHUSDT", 1, 201)], L, 0, 10000)
    assert y["status"] == "no_sync"
    reversed_events = [(10000, "BTCUSDT", 1, 99.8), (10000, "ETHUSDT", 1, 179.8),
                       (11001, "BTCUSDT", 2, 99.7), (11001, "ETHUSDT", 2, 179.7)]
    # Both symbols must break the same direction.
    assert find_sync(reversed_events, L, 0, 30000)["status"] == "no_sync"
    decline = [(10000, "BTCUSDT", 1, 89.8), (10000, "ETHUSDT", 1, 179.8),
               (11001, "BTCUSDT", 2, 89.7), (11001, "ETHUSDT", 2, 179.7)]
    assert find_sync(decline, L, 0, 30000)["side"] == -1
    rejected = [(10000, "BTCUSDT", 1, 100.2), (10000, "ETHUSDT", 1, 200.2),
                (11001, "BTCUSDT", 2, 99.9), (11001, "ETHUSDT", 2, 200.3)]
    assert find_sync(rejected, L, 0, 30000)["status"] == "confirmation_rejected"
    signal = {"status": "confirmed", "side": 1, "signal_ts": 10001, "reference_ts": 11002,
              "signal_prices": {"BTCUSDT": "100.2", "ETHUSDT": "200.2"},
              "reference_prices": {"BTCUSDT": "100.3", "ETHUSDT": "200.3"}}
    ticks = [(12002, 1, 100.31), (15000, 2, 101.3), (20000, 3, 100.9), (35000, 4, 100)]
    z = simulate_path(ticks, signal, L, "BTCUSDT", "1", 20, 1, 30000)
    assert z["status"] == "verified" and z["reason"] == "target" and z["exit_signal_ts"] == 15000 and z["exit_ts"] == 20000
    z2 = simulate_path(ticks, signal, L, "BTCUSDT", "1", 20, 2, 30000)
    assert z2["status"] == "verified" and z2["reason"] == "quarter_time" and z2["exit_ts"] == 35000
    assert simulate_path(ticks, signal, L, "BTCUSDT", ".01", 20, 1, 30000)["status"] == "known_risk_rejected"
    same_ms = [(12002, 1, 100.31), (15000, 2, 99.4), (15000, 3, 101.4), (20000, 4, 100)]
    assert simulate_path(same_ms, signal, L, "BTCUSDT", "1", 20, 1, 30000)["reason"] == "stop"
    out = {"all_checks_pass": True, "engine_sha256": sha(H / "dual_pilot_engine.py"), "test_sha256": sha(Path(__file__)),
           "cases": ["same-ms dual updates", "stale quote", "opposite directions", "short", "confirmation fails", "delayed 1r and 2r", "risk precheck", "same-ms stop priority"]}
    (H / "双币试点合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
