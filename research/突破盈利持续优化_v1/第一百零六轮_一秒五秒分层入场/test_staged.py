import json
from pathlib import Path

from run_staged import H, choose_target, net_value, sha, stage_branch
from decimal import Decimal


def main():
    assert stage_branch("entered", "entered", 1000, 5000)[0] == "early"
    assert stage_branch("unknown", "entered", None, 5000)[0] == "unknown"
    assert stage_branch("rejected", "unknown", 1000, 5000)[0] == "unknown"
    assert stage_branch("rejected", "rejected", 1000, 5000)[0] == "no_order"
    assert stage_branch("rejected", "entered", 1000, 5000)[0] == "late"
    assert stage_branch("rejected", "entered", 5001, 5000)[0] == "unknown"
    assert stage_branch("rejected", "entered", None, 5000)[0] == "unknown"
    assert stage_branch("rejected", "entered", 5000, 5000)[0] == "late"
    assert choose_target("staged_adaptive", "early", 0.49999) == 1
    assert choose_target("staged_adaptive", "early", 0.5) == 2
    assert choose_target("staged_1r", "late", 0.2) == 2
    long = {"entry_fill": 100, "exit_raw": 101, "side": 1, "funding": 0}
    short = {"entry_fill": 100, "exit_raw": 99, "side": -1, "funding": 0}
    assert net_value(long, Decimal(".0005")) > 0
    assert net_value(short, Decimal(".0005")) > 0
    assert net_value(long, Decimal(".001")) < net_value(long, Decimal(".0005"))
    assert net_value(short, Decimal(".001")) < net_value(short, Decimal(".0005"))
    out = {"all_checks_pass": True, "code_sha256": sha(H / "run_staged.py"),
           "test_sha256": sha(Path(__file__)),
           "cases": ["early priority", "unknown not fallback", "late rejection", "late information", "equal threshold", "long short costs"]}
    (H / "合成时序核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
