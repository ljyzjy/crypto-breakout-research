"""Additional conservative path checks; no observed market outcomes used."""
import hashlib
import json
from pathlib import Path

from dual_pilot_engine import find_sync, simulate_path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    levels = {"BTCUSDT": {"upper": 100, "lower": 90}, "ETHUSDT": {"upper": 200, "lower": 180}}
    not_simultaneous = [(10000, "BTCUSDT", 1, 101), (10000, "ETHUSDT", 1, 199),
                        (10500, "BTCUSDT", 2, 99.9), (11000, "ETHUSDT", 2, 201)]
    assert find_sync(not_simultaneous, levels, 0, 30000)["status"] == "no_sync"
    same_ms_retrace = [(10000, "BTCUSDT", 1, 101), (10000, "BTCUSDT", 2, 99.9), (10000, "ETHUSDT", 1, 201)]
    assert find_sync(same_ms_retrace, levels, 0, 30000)["status"] == "no_sync"
    clean = [(10000, "BTCUSDT", 1, 101), (10000, "ETHUSDT", 1, 201),
             (11001, "BTCUSDT", 2, 101.1), (11001, "ETHUSDT", 2, 201.1)]
    assert find_sync(clean, levels, 0, 30000) == find_sync(clean + [(20000, "BTCUSDT", 3, 80)], levels, 0, 30000)
    signal = {"status": "confirmed", "side": 1, "signal_ts": 10001, "reference_ts": 11002,
              "signal_prices": {"BTCUSDT": "100.2", "ETHUSDT": "200.2"},
              "reference_prices": {"BTCUSDT": "100.3", "ETHUSDT": "200.3"}}
    gap = [(12002, 1, 99), (17002, 2, 98.8)]
    path = simulate_path(gap, signal, levels, "BTCUSDT", 1, 20, 1, 30000)
    assert path["status"] == "verified" and path["reason"] == "filled_beyond_risk_budget"
    assert path["exit_signal_ts"] == path["entry_ts"] and path["exit_ts"] >= path["exit_signal_ts"] + 5000
    assert simulate_path(gap[:1], signal, levels, "BTCUSDT", 1, 20, 1, 30000)["status"] == "unknown_delayed_exit"
    assert simulate_path([(30000, 1, 100)], signal, levels, "BTCUSDT", 1, 20, 1, 30000)["status"] == "unknown_delayed_entry"
    out = {"all_checks_pass": True, "engine_sha256": sha(H / "dual_pilot_engine.py"), "test_sha256": sha(Path(__file__)),
           "cases": ["nonoverlapping breakouts", "same-ms retrace", "future perturbation", "paid gap exit", "missing delayed fill", "missing entry"]}
    (H / "双币试点补充核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
