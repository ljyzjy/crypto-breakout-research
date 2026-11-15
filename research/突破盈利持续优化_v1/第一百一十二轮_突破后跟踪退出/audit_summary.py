"""Independently recompute paired unit metrics and ex-post label groups."""
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R102 = P / "第一百零二轮_大柱持有损益核查"
R108 = P / "第一百零八轮_原始逐笔一倍与动态止盈"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True)
    result = json.loads((H / "跟踪退出配对结果.json").read_text(encoding="utf-8"))
    assert result["code_sha256"] == bulk.sha(H / "summarize_trailing.py")
    assert result["detail_sha256"] == bulk.sha(H / "跟踪退出配对明细.csv")
    raw = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet")
    one = pd.read_parquet(R108 / "一倍止盈单位账本.parquet")
    trailing = pd.read_parquet(H / "跟踪退出单位账本.parquet")
    names = {"original_2r": raw, "one_r": one, "trailing": trailing}
    detail = pd.read_csv(H / "跟踪退出配对明细.csv")
    checked = 0
    for row in result["rows"]:
        lev = row["leverage"]
        cohort = detail[detail.leverage == lev]
        if row["rule"].startswith("label_"):
            category = row["rule"][6:]
            group = cohort[cohort.label == category]
            assert len(group) == row["paths"]
            assert (group.trailing_action == "trailing_exit").sum() == row["trailing_earlier"]
            for field, col in (("original_mean_net_pct", "original_net"), ("one_r_mean_net_pct", "one_r_net"), ("trailing_mean_net_pct", "trailing_net")):
                if len(group):
                    assert abs(row[field] - 100 * group[col].mean()) < 1e-10
                else:
                    assert row[field] is None
        else:
            src = names[row["rule"]]
            variant = f"one_observation_2r_{lev}x"
            sub = src[(src.variant == variant) & (src.observation_id.isin(cohort.observation_id))].copy()
            assert len(sub) == len(cohort) == row["trades"]
            slip = row["exit_slippage_pct"] / 100
            exit_ = sub.exit_raw * (1 - sub.side * slip)
            net = sub.side * (exit_ - sub.entry_fill) / sub.entry_fill - .0005 * (1 + exit_ / sub.entry_fill) - sub.funding
            assert int((net > 0).sum()) == row["wins"]
            assert abs(100 * (net > 0).mean() - row["win_rate_pct"]) < 1e-10
            assert abs(100 * net.mean() - row["mean_net_pct_notional"]) < 1e-10
            if (net < 0).any():
                assert abs(net[net > 0].sum() / -net[net < 0].sum() - row["profit_factor"]) < 1e-10
            checked += len(sub)
    out = {"all_checks_pass": True, "groups_checked": len(result["rows"]), "path_group_recalculations": checked,
           "summary_sha256": bulk.sha(H / "跟踪退出配对结果.json"), "code_sha256": bulk.sha(Path(__file__))}
    (H / "跟踪退出汇总独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
