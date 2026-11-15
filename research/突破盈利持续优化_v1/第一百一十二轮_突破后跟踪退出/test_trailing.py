import hashlib
import json
from pathlib import Path
from trailing import apply

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    path = {"entry_ts": 1000, "exit_signal_ts": 20000, "exit_ts": 25000, "entry_raw": 100,
            "entry_fill": 100, "exit_raw": 100.2, "side": 1, "actual_entry_risk": 1}
    seq = [(1000, 100), (2000, 101), (3000, 101.5), (4000, 100.74), (8999, 102), (9000, 100.6), (25000, 100.2)]
    out = apply(path, seq)
    assert out["action"] == "trailing_exit" and out["exit_signal_ts"] == 4000 and out["exit_ts"] == 9000
    short = {**path, "side": -1, "exit_raw": 99.8}
    short_seq = [(1000, 100), (2000, 99), (3000, 98.5), (4000, 99.26), (9000, 99.4), (25000, 99.8)]
    so = apply(short, short_seq)
    assert so["action"] == "trailing_exit" and so["exit_signal_ts"] == 4000 and so["exit_ts"] == 9000
    same = [(1000, 100), (2000, 101.5), (2000, 100), (3000, 100.8), (4000, 100.74), (9000, 100.6), (25000, 100.2)]
    assert apply(path, same)["exit_signal_ts"] == 4000
    priority = {**path, "exit_signal_ts": 4000, "exit_ts": 9000, "exit_raw": 100.6}
    assert apply(priority, seq)["action"] == "original"
    assert apply({**path, "exit_signal_ts": 1000}, [])["reason"] == "original_signal_first"
    assert apply(path, [(1001, 100), (25000, 100.2)])["reason"] == "missing_entry_reference"
    invalid = [(1000, 100), (2000, 101), (3000, 100.24)]
    assert apply(path, invalid)["reason"] == "original_exit_reference_mismatch"
    proof = {"all_checks_pass": True, "engine_sha256": sha(H / "trailing.py"), "test_sha256": sha(Path(__file__)),
             "cases": ["long", "short", "five second delay", "same millisecond grouping", "original priority", "missing ticks"]}
    (H / "跟踪退出合成核验.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
