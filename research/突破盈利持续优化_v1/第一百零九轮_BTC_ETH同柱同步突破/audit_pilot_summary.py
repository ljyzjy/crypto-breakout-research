"""Independently recalculate all pilot summary metrics and unknown counts."""
from collections import Counter
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def near(a, b):
    return a is b if a is None or b is None else abs(D(str(a)) - D(str(b))) < D("1e-10")


def main():
    result_file = H / "三日双币试点结果.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    for key, name in (("paths_sha256", "三日逐笔路径.json"), ("ledger_sha256", "三日单位风险账本.json"),
                      ("path_audit_sha256", "三日逐笔独立样本核验.json"), ("risk_audit_sha256", "三日风险独立核验.json"),
                      ("code_sha256", "summarize_pilot.py")):
        assert result[key] == sha(H / name)
    paths = json.loads((H / "三日逐笔路径.json").read_text(encoding="utf-8"))
    ledger = json.loads((H / "三日单位风险账本.json").read_text(encoding="utf-8"))
    assert result["days"] == paths["days"] and result["candidate_quarters"] == len(paths["signals"])
    statuses = Counter(x["status"] for x in paths["signals"])
    assert dict(statuses) == result["quarter_statuses"]
    assert len(ledger["ledger"]) == len(paths["paths"]) == 8 * statuses.get("confirmed", 0)
    for p in ledger["ledger"]:
        if p["category"] != "trade":
            continue
        assert p["risk_status"] == "verified" and not p["liq_proxy"]
        entry, exit_, side = D(str(p["entry_fill"])), D(str(p["exit_fill"])), D(p["side"])
        net = side * (exit_ - entry) / entry - D(".0005") - D(".0005") * exit_ / entry - D(str(p["funding"]))
        assert near(net, p["net_per_unit_notional"])
    for row in result["rows"]:
        lev, target, sym = row["leverage"], row["target_r"], row["symbol"]
        group = [p for p in ledger["ledger"] if p["leverage"] == lev and p["target_r"] == target and (sym == "all" or p["contract"] == sym)]
        good = [p for p in group if p["category"] == "trade"]
        slip = D(str(row["exit_slippage_pct"])) / 100
        values = []
        for p in good:
            entry, side = D(str(p["entry_fill"])), D(p["side"])
            exit_ = D(str(p["exit_raw"])) * (1 - side * slip)
            values.append(side * (exit_ - entry) / entry - D(".0005") * (1 + exit_ / entry) - D(str(p["funding"])))
        wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
        assert row["confirmed_signal_paths"] == len(group) and row["trades"] == len(good) and row["wins"] == len(wins)
        assert row["no_order"] == sum(p["category"] == "no_order" for p in group)
        assert row["unknown_paths"] == sum(p["category"] in ("unknown_path", "unknown_risk") for p in group)
        assert near(row["net_win_rate_pct"], D(100) * len(wins) / len(values) if values else None)
        assert near(row["mean_net_pct_notional"], D(100) * sum(values, D(0)) / len(values) if values else None)
        assert near(row["profit_factor"], sum(wins, D(0)) / -sum(losses, D(0)) if losses else None)
    out = {"all_checks_pass": True, "groups_checked": len(result["rows"]), "path_classifications_checked": len(ledger["ledger"]),
           "result_sha256": sha(result_file), "audit_code_sha256": sha(Path(__file__)),
           "note": "Unit metrics and unknowns independently checked; three days are exploratory and not a portfolio."}
    (H / "三日结果独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
