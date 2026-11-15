import hashlib
import json
from pathlib import Path

from oracle_exit import evaluate

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    path = {"side": 1, "entry_ts": 1000, "entry_raw": "100", "entry_fill": "100.05", "initial_stop": "99", "reason": "target"}
    # A price before the 5s latency is unattainable; prices after the stop-fill
    # deadline cannot be credited even if they subsequently recover.
    ticks = [(1000, 100), (2000, 110), (6000, 101), (7000, 98.9), (8000, 120), (12000, 98), (13000, 130)]
    a = evaluate(path, ticks, 20000)
    assert a["status"] == "known" and a["deadline_ts"] == 7000 and a["forced_exit_ts"] == 12000
    assert a["oracle_exit_ts"] == 8000
    forced = evaluate({**path, "reason": "filled_beyond_risk_budget"}, ticks, 20000)
    assert forced["oracle_exit_ts"] == 6000 and forced["deadline_ts"] == 1000
    short = {**path, "side": -1, "initial_stop": "101", "entry_fill": "99.95"}
    s = evaluate(short, [(1000, 100), (6000, 99), (7000, 101.1), (12000, 100)], 20000)
    assert s["status"] == "known" and s["oracle_exit_ts"] == 6000
    assert evaluate(path, [(1001, 100), (6000, 101)], 20000)["status"] == "unknown_entry_tick"
    assert evaluate(path, [(1000, 100), (7000, 98)], 20000)["status"] == "unknown_forced_exit"
    out = {"all_checks_pass": True, "engine_sha256": sha(H / "oracle_exit.py"), "test_sha256": sha(Path(__file__)),
           "cases": ["five-second delay", "stop deadline", "forced budget exit", "short", "missing entry", "missing forced fill"]}
    (H / "退出上界合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
