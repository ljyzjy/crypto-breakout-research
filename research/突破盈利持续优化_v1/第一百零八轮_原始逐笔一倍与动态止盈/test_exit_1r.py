"""Small synthetic checks, using no historical archives."""
from pathlib import Path
import hashlib
import json

from exit_1r import apply

H = Path(__file__).resolve().parent


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    base = {"entry_ts": 1000, "exit_signal_ts": 12000, "side": 1, "entry_fill": 100, "actual_entry_risk": 1}
    long = apply(base, [(1000, 100), (3000, 101), (7999, 101), (8000, 100.5), (17000, 99)])
    assert long["action"] == "one_r_exit" and long["exit_signal_ts"] == 3000 and long["exit_ts"] == 8000
    assert abs(long["exit_fill"] - 100.44975) < 1e-10
    short = apply({**base, "side": -1}, [(1000, 100), (3000, 99), (8000, 99.5)])
    assert short["action"] == "one_r_exit" and abs(short["exit_fill"] - 99.54975) < 1e-10
    assert apply(base, [(1000, 100), (12000, 101), (17000, 100)])["action"] == "original"
    assert apply({**base, "exit_signal_ts": 1000}, [(1000, 101)])["action"] == "original"
    assert apply(base, [(1001, 100), (3000, 101), (8000, 100)])["reason"] == "missing_entry_reference"
    assert apply({**base, "entry_raw": 100.5}, [(1000, 100), (3000, 101), (8000, 100)])["reason"] == "entry_reference_mismatch"
    assert apply({**base, "exit_ts": 17000, "exit_raw": 100}, [(1000, 100), (3000, 101), (8000, 100)])["reason"] == "original_exit_reference_mismatch"
    assert apply(base, [(1000, 100), (3000, 101)])["reason"] == "missing_delayed_exit"
    assert apply({**base, "actual_entry_risk": 0}, [(1000, 100)])["reason"] == "invalid_actual_risk"
    try:
        apply(base, [(1001, 100), (1000, 101)])
        raise AssertionError("unordered timestamps accepted")
    except ValueError:
        pass
    out = {"all_checks_pass": True, "engine_sha256": sha(H / "exit_1r.py"), "test_sha256": sha(Path(__file__)),
           "cases": ["long and short", "same-ms original priority", "immediate risk exit", "missing fill", "invalid risk", "timestamp order"]}
    (H / "一倍止盈合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
