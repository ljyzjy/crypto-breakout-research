from pathlib import Path
import json

from run_retry_combo import H, retry_decision, sha


def main():
    assert retry_decision("trade", True, "entered", 1000, 5000, 6000, 11000)[0] == "prior"
    assert retry_decision("unknown", True, "entered", 1000, 5000, 6000, 11000)[0] == "prior"
    assert retry_decision("no_order", False, "entered", 1000, 5000, 6000, 11000)[0] == "no_order"
    assert retry_decision("no_order", True, "unknown", 1000, 5000, 6000, 11000)[0] == "unknown"
    assert retry_decision("no_order", True, "rejected", 1000, 5000, 6000, 11000)[0] == "no_order"
    assert retry_decision("no_order", True, "entered", 1000, 5000, 6000, 11000)[0] == "retry"
    assert retry_decision("no_order", True, "entered", 11001, 5000, 6000, 11000)[0] == "unknown"
    assert retry_decision("no_order", True, "entered", 1000, 5000, 5000, 10000)[0] == "unknown"
    assert retry_decision("no_order", True, "entered", 1000, 5000, 6000, 10999)[0] == "unknown"
    assert retry_decision("no_order", True, "entered", None, 5000, 6000, 11000)[0] == "unknown"
    result = {"all_checks_pass": True, "code_sha256": sha(H / "run_retry_combo.py"),
              "test_sha256": sha(Path(__file__)),
              "cases": ["one order only", "unknown not rejection", "retry eligibility", "late information", "strict rebreakout time", "confirmation delay"]}
    (H / "合成时序核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
