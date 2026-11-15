"""Report upper bounds for frozen 2022 candidate entries, not strategies."""
from collections import Counter
from decimal import Decimal as D
import json
from pathlib import Path

import pandas as pd
import run_oracle as base

H = Path(__file__).resolve().parent


def main():
    detail = json.loads((H / "退出上界逐笔.json").read_text(encoding="utf-8"))
    proof = json.loads((H / "退出上界独立核验.json").read_text(encoding="utf-8"))
    funding_test = json.loads((H / "资金费边界合成核验.json").read_text(encoding="utf-8"))
    assert proof["all_checks_pass"] and proof["source_sha256"] == base.bulk.sha(H / "退出上界逐笔.json")
    assert proof["code_sha256"] == base.bulk.sha(H / "audit_oracle.py")
    assert funding_test["all_checks_pass"] and funding_test["runner_sha256"] == base.bulk.sha(H / "run_oracle.py")
    assert funding_test["audit_sha256"] == base.bulk.sha(H / "audit_oracle.py")
    prior = pd.read_csv(base.R98 / "候选状态与单位账本.csv", dtype=str, keep_default_na=False)
    groups = []
    for lev in (10, 20):
        rows = [x for x in detail["rows"] if x["leverage"] == lev]
        known = [x for x in rows if x["status"] == "known"]
        n_unknown_prior = sum((prior.leverage == str(lev)) & (prior.category == "unknown"))
        unknown = len(rows) - len(known) + int(n_unknown_prior)
        wins = sum(D(x["oracle_net"]) > 0 for x in known)
        theoretical_wins = wins + unknown
        total = len(known) + unknown
        target_max = min(total, (5 * theoretical_wins - 1) // 3) if theoretical_wins else 0
        assert len(rows) + int(n_unknown_prior) == total
        groups.append({"leverage": lev, "original_trade_paths": len(rows), "known_zero_funding_paths": len(known),
                       "known_future_aware_wins": wins, "known_future_aware_win_rate": str(D(wins) / D(len(known))) if known else None,
                       "mean_future_aware_notional_return": str(sum((D(x["oracle_net"]) for x in known), D(0)) / D(len(known))) if known else None,
                       "mean_original_notional_return_same_known_paths": str(sum((D(x["baseline_net"]) for x in known), D(0)) / D(len(known))) if known else None,
                       "new_unknown_statuses": dict(Counter(x["status"] for x in rows if x["status"] != "known")),
                       "original_unknown_candidates": int(n_unknown_prior), "all_unknown_assumed_wins": unknown,
                       "potential_fixed_entry_paths": total, "maximum_possible_wins_if_unknown_win": theoretical_wins,
                       "upper_win_rate_with_at_least_100_trades": str(D(min(100, theoretical_wins)) / D(100)) if total >= 100 else None,
                       "max_trade_count_strictly_over_60pct": target_max})
    out = {"groups": groups, "raw_detail_sha256": base.bulk.sha(H / "退出上界逐笔.json"),
           "independent_audit_sha256": base.bulk.sha(H / "退出上界独立核验.json"),
           "code_sha256": base.bulk.sha(Path(__file__)),
           "scope": "Fixed 2022 listed entries, one stop and quarter horizon, 5s exit delay; original ranking has 240 unknown hours.",
           "note": "Perfect hindsight, unknowns assumed winners, ignoring liquidation and shared capital: not a tradable result."}
    (H / "退出上界汇总.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
