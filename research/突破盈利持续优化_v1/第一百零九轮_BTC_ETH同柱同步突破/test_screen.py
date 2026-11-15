import json
from pathlib import Path

import pandas as pd

from screen_candidates import H, Q, possible_quarters, sha


def main():
    idx = pd.Index([i * Q for i in range(20)], name="quarter")
    b = pd.DataFrame({"high": [100.] * 20, "low": [90.] * 20, "valid": [True] * 20}, index=idx)
    e = pd.DataFrame({"high": [200.] * 20, "low": [180.] * 20, "valid": [True] * 20}, index=idx)
    b.loc[16 * Q, "high"], e.loc[16 * Q, "high"] = 101., 201.
    b.loc[16 * Q, "low"], e.loc[16 * Q, "low"] = 89., 179.
    a = possible_quarters(b, e)
    assert a.loc[16 * Q, "known"] and a.loc[16 * Q, "possible_long"] and a.loc[16 * Q, "possible_short"]
    assert a.loc[16 * Q, "btc_upper"] == 100 and a.loc[16 * Q, "eth_upper"] == 200
    changed = b.copy()
    changed.loc[16 * Q, "high"] = 500.
    assert possible_quarters(changed, e).loc[16 * Q, "btc_upper"] == 100
    equal_b, equal_e = b.copy(), e.copy()
    equal_b.loc[16 * Q, "high"], equal_e.loc[16 * Q, "high"] = 100., 200.
    assert not possible_quarters(equal_b, equal_e).loc[16 * Q, "possible_long"]
    missing = b.drop(index=8 * Q)
    assert not possible_quarters(missing, e).loc[16 * Q, "known"]
    invalid = b.copy()
    invalid.loc[16 * Q, "valid"] = False
    assert not possible_quarters(invalid, e).loc[16 * Q, "known"]
    out = {"all_checks_pass": True, "code_sha256": sha(H / "screen_candidates.py"), "test_sha256": sha(Path(__file__)),
           "cases": ["past-only levels", "strict equality", "both directions retained", "missing quarter", "invalid current quarter"]}
    (H / "候选合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
