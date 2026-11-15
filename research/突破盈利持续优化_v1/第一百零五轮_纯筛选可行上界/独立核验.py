from __future__ import annotations

import csv
import hashlib
import heapq
import json
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent
DETAIL = HERE.parent / "第九十八轮_二零二二原始逐笔全样本" / "候选状态与单位账本.csv"
SOURCE = DETAIL.parent
RESULT = HERE / "纯筛选可行上界.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_threshold(wins: int, count: int) -> bool:
    return 5 * wins > 3 * count


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["detail_sha256"] == sha(DETAIL)
    source_summary = SOURCE / "原始逐笔汇总.json"
    source_audit = SOURCE / "原始逐笔汇总独立核验.json"
    assert result["source_summary_sha256"] == sha(source_summary)
    assert result["source_audit_sha256"] == sha(source_audit)
    assert result["research_plan_sha256"] == sha(HERE / "分析方案.md")
    assert result["analysis_code_sha256"] == sha(HERE / "可行上界.py")
    original_audit = json.loads(source_audit.read_text(encoding="utf-8"))
    assert original_audit["all_checks_pass"] is True
    assert original_audit["detail_sha256"] == sha(DETAIL)
    assert original_audit["report_sha256"] == sha(source_summary)
    with DETAIL.open(encoding="utf-8-sig", newline="") as stream:
        raw = list(csv.DictReader(stream))
    assert not check_threshold(60, 100)
    assert check_threshold(61, 100)
    assert check_threshold(34, 56)
    assert not check_threshold(34, 57)
    checked = []
    for group in result["results"]:
        leverage = group["leverage"]
        selected = [r for r in raw if r["leverage"] == str(leverage)]
        values = [Decimal(r["net"]) for r in selected if r["category"] == "trade"]
        winners = len([v for v in values if v > 0])
        unknown = len([r for r in selected if r["category"] == "unknown"])
        assert (len(values), winners, unknown) == (
            group["known_trades"], group["known_net_wins"], group["original_unknown_candidates"])
        capacity = len(values) + unknown
        winning_capacity = winners + unknown
        # Enumerate every allowed size, independently of the closed form.
        candidates = [(Decimal(min(winning_capacity, n)) * 100 / n, n)
                      for n in range(100, capacity + 1)]
        max_rate, max_rate_n = max(candidates)
        feasible_counts = [n for n in range(1, capacity + 1)
                           if check_threshold(min(winning_capacity, n), n)]
        assert max_rate == Decimal(group["min_100_trades_optimistic_max_net_win_rate_pct"])
        assert max(feasible_counts) == group["strictly_above_60pct_max_trade_count"]
        best = heapq.nlargest(100, values)
        assert sum(best) == Decimal(group["oracle_known_only_top100_mean_net_pct_notional"])
        assert best[-1] * 100 == Decimal(group["oracle_known_only_100th_net_pct_notional"])
        positive = [v for v in values if v > 0]
        nonpositive = [v for v in values if v <= 0]
        mean_positive = sum(positive) / len(positive)
        mean_nonpositive = sum(nonpositive) / len(nonpositive)
        static_rate = -mean_nonpositive / (mean_positive - mean_nonpositive) * 100
        assert mean_positive * 100 == Decimal(group["known_mean_win_pct_notional"])
        assert mean_nonpositive * 100 == Decimal(group["known_mean_nonwin_pct_notional"])
        assert static_rate == Decimal(group["known_static_break_even_win_rate_pct"])
        checked.append({"leverage": leverage, "enumerated_trade_counts": capacity,
                        "max_rate_at_n": max_rate_n, "optimistic_max_rate_pct": str(max_rate),
                        "max_count_above_60": max(feasible_counts)})
    out = {"all_checks_pass": True, "result_sha256": sha(RESULT), "detail_sha256": sha(DETAIL),
           "analysis_code_sha256": sha(HERE / "可行上界.py"), "audit_code_sha256": sha(Path(__file__).resolve()),
           "integer_threshold_tests_pass": True, "groups": checked,
           "note": "Independent size enumeration and top-100 heap arithmetic; result remains scoped to frozen known paths."}
    (HERE / "纯筛选可行上界独立核验.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
