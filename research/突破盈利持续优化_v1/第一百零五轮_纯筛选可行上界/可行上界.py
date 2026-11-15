from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "第九十八轮_二零二二原始逐笔全样本"
DETAIL = SOURCE / "候选状态与单位账本.csv"
SUMMARY = SOURCE / "原始逐笔汇总.json"
AUDIT = SOURCE / "原始逐笔汇总独立核验.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    detail_sha = digest(DETAIL)
    assert audit["all_checks_pass"] is True
    assert audit["detail_sha256"] == detail_sha == summary["detail_sha256"]
    assert audit["report_sha256"] == digest(SUMMARY)
    assert summary["candidate_count"] == 310
    assert summary["unknown_rank_hours_original"] == 240
    with DETAIL.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    results = []
    for leverage in (10, 20):
        subset = [r for r in rows if int(r["leverage"]) == leverage]
        assert len(subset) == 310
        assert len({r["observation_id"] for r in subset}) == 310
        assert {r["category"] for r in subset} == {"trade", "unknown", "no_order"}
        trades = [r for r in subset if r["category"] == "trade"]
        unknown = sum(r["category"] == "unknown" for r in subset)
        no_order = sum(r["category"] == "no_order" for r in subset)
        net = [Decimal(r["net"]) for r in trades]
        assert all(n.is_finite() for n in net)
        wins = sum(n > 0 for n in net)
        reference = next(r for r in summary["rows"]
                         if r["leverage"] == leverage and r["exit_slippage_pct"] == 0.05)
        assert (len(trades), wins, unknown, no_order) == (
            reference["trades"], reference["net_wins"],
            reference["unknown_candidates"], reference["known_no_order"])
        mean_pct = sum(net) * 100 / len(net)
        assert abs(mean_pct - Decimal(str(reference["mean_net_pct_notional"]))) < Decimal("1e-12")
        assert len(trades) + unknown >= 100

        # An impossible-to-implement perfect selector can retain all known wins
        # and assume every originally unknown candidate becomes a winning trade.
        upper_wins = wins + unknown
        assert upper_wins <= 100
        max_trade_count_above_60 = min(len(trades) + unknown, (5 * upper_wins - 1) // 3)
        assert max_trade_count_above_60 >= upper_wins
        oracle_top100 = sorted(net, reverse=True)[:100]
        positive = [n for n in net if n > 0]
        nonpositive = [n for n in net if n <= 0]
        mean_win = sum(positive) / len(positive)
        mean_nonwin = sum(nonpositive) / len(nonpositive)
        assert mean_win > 0 and mean_nonwin < 0
        results.append({
            "leverage": leverage,
            "known_trades": len(trades),
            "known_net_wins": wins,
            "original_unknown_candidates": unknown,
            "known_no_orders": no_order,
            "optimistic_max_wins": upper_wins,
            "min_100_trades_optimistic_max_net_win_rate_pct": str(Decimal(upper_wins)),
            "strictly_above_60pct_max_trade_count": max_trade_count_above_60,
            "strictly_above_60pct_wins_required_at_100": 61,
            "known_mean_win_pct_notional": str(mean_win * 100),
            "known_mean_nonwin_pct_notional": str(mean_nonwin * 100),
            "known_static_break_even_win_rate_pct": str((-mean_nonwin / (mean_win - mean_nonwin)) * 100),
            "oracle_known_only_top100_mean_net_pct_notional": str(sum(oracle_top100) * 100 / 100),
            "oracle_known_only_100th_net_pct_notional": str(oracle_top100[-1] * 100),
        })
    out = {
        "scope": "2022 listed candidates, original raw one-second entry and fixed 2R paths; fixed exit slippage 0.05%; filter existing trade paths only",
        "unknown_rank_hours_original_excluded": 240,
        "detail_sha256": detail_sha,
        "source_summary_sha256": digest(SUMMARY),
        "source_audit_sha256": digest(AUDIT),
        "research_plan_sha256": digest(HERE / "分析方案.md"),
        "analysis_code_sha256": digest(Path(__file__).resolve()),
        "results": results,
        "note": "Post-hoc mathematical oracle, not a deployable filter or profit result; unknown candidates assumed wins only in the win-rate bound. The known-only profit oracle excludes unknowns, is not an account result, and is not a bound if unknown returns are included.",
    }
    (HERE / "纯筛选可行上界.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
