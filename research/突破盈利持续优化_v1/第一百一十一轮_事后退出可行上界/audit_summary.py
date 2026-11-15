"""Independent group arithmetic for the optimistic bound."""
import json
from pathlib import Path

import pandas as pd
import run_oracle as base

H = Path(__file__).resolve().parent


def main():
    result = json.loads((H / "退出上界汇总.json").read_text(encoding="utf-8"))
    meta = json.loads((H / "退出上界逐笔.json").read_text(encoding="utf-8"))
    assert result["raw_detail_sha256"] == base.bulk.sha(H / "退出上界逐笔.json")
    assert result["code_sha256"] == base.bulk.sha(H / "summarize_oracle.py")
    df = pd.DataFrame(meta["rows"])
    prior = pd.read_csv(base.R98 / "候选状态与单位账本.csv")
    for item in result["groups"]:
        lev = item["leverage"]
        d = df[df.leverage == lev]
        k = d[d.status == "known"]
        n, w = len(k), int((pd.to_numeric(k.oracle_net) > 0).sum())
        prior_unknown = len(prior[(prior.leverage == lev) & (prior.category == "unknown")])
        u, total = len(d) - n + prior_unknown, len(d) + prior_unknown
        max_w = w + u
        assert (len(d), n, w, u, total) == (item["original_trade_paths"], item["known_zero_funding_paths"], item["known_future_aware_wins"], item["all_unknown_assumed_wins"], item["potential_fixed_entry_paths"])
        assert abs(float(item["mean_future_aware_notional_return"]) - pd.to_numeric(k.oracle_net).mean()) < 1e-12
        assert abs(float(item["mean_original_notional_return_same_known_paths"]) - pd.to_numeric(k.baseline_net).mean()) < 1e-12
        if total >= 100:
            assert abs(float(item["upper_win_rate_with_at_least_100_trades"]) - min(max_w, 100) / 100) < 1e-12
        feasible = [count for count in range(1, total + 1) if 5 * min(count, max_w) > 3 * count]
        assert item["max_trade_count_strictly_over_60pct"] == max(feasible, default=0)
    out = {"all_checks_pass": True, "groups_checked": len(result["groups"]), "rows_checked": len(df),
           "summary_sha256": base.bulk.sha(H / "退出上界汇总.json"), "code_sha256": base.bulk.sha(Path(__file__))}
    (H / "退出上界汇总独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
