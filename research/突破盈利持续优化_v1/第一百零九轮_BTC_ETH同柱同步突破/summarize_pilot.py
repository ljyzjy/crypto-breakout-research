"""Summarize only after independent raw-sample and mark/funding audits."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D
import json
from pathlib import Path

H = Path(__file__).resolve().parent
import hashlib


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def calc(record, slip):
    entry, raw, side = D(str(record["entry_fill"])), D(str(record["exit_raw"])), D(int(record["side"]))
    exit_ = raw * (1 - side * slip)
    return side * (exit_ / entry - 1) - D(".0005") * (1 + exit_ / entry) - D(str(record["funding"]))


def main():
    paths = json.loads((H / "三日逐笔路径.json").read_text(encoding="utf-8"))
    ledger = json.loads((H / "三日单位风险账本.json").read_text(encoding="utf-8"))
    path_audit = json.loads((H / "三日逐笔独立样本核验.json").read_text(encoding="utf-8"))
    risk_audit = json.loads((H / "三日风险独立核验.json").read_text(encoding="utf-8"))
    assert path_audit["all_checks_pass"] and path_audit["paths_sha256"] == sha(H / "三日逐笔路径.json")
    assert path_audit["code_sha256"] == sha(H / "audit_pilot_paths.py")
    assert risk_audit["all_checks_pass"] and risk_audit["ledger_sha256"] == sha(H / "三日单位风险账本.json")
    assert risk_audit["audit_code_sha256"] == sha(H / "audit_pilot_risk.py")
    assert ledger["paths_sha256"] == sha(H / "三日逐笔路径.json")
    rows = []
    for lev in (10, 20):
        for target in (1, 2):
            for symbol in ("all", "BTCUSDT", "ETHUSDT"):
                group = [x for x in ledger["ledger"] if x["leverage"] == lev and x["target_r"] == target
                         and (symbol == "all" or x["contract"] == symbol)]
                good = [x for x in group if x["category"] == "trade"]
                for pct in (D(".0005"), D(".00075"), D(".001")):
                    vals = [calc(x, pct) for x in good]
                    positive = sum((v for v in vals if v > 0), D(0))
                    negative = -sum((v for v in vals if v < 0), D(0))
                    rows.append({"leverage": lev, "target_r": target, "symbol": symbol, "exit_slippage_pct": float(100 * pct),
                                 "confirmed_signal_paths": len(group), "trades": len(good), "wins": sum(v > 0 for v in vals),
                                 "net_win_rate_pct": float(D(100) * sum(v > 0 for v in vals) / len(vals)) if vals else None,
                                 "mean_net_pct_notional": float(D(100) * sum(vals, D(0)) / len(vals)) if vals else None,
                                 "profit_factor": float(positive / negative) if negative else None,
                                 "no_order": sum(x["category"] == "no_order" for x in group),
                                 "unknown_paths": sum(x["category"] in ("unknown_path", "unknown_risk") for x in group)})
    q = Counter(x["status"] for x in paths["signals"])
    result = {"days": paths["days"], "candidate_quarters": paths["candidate_quarters"], "quarter_statuses": dict(q),
              "rows": rows, "paths_sha256": sha(H / "三日逐笔路径.json"), "ledger_sha256": sha(H / "三日单位风险账本.json"),
              "path_audit_sha256": sha(H / "三日逐笔独立样本核验.json"), "risk_audit_sha256": sha(H / "三日风险独立核验.json"),
              "code_sha256": sha(Path(__file__)),
              "note": "Three days, historical fixed pilot, correlated signals, no shared account, true execution or independent future data."}
    (H / "三日双币试点结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        if row["leverage"] == 20 and row["symbol"] == "all" and row["exit_slippage_pct"] == .05:
            print("EXT109_PILOT_RESULT", json.dumps(row, ensure_ascii=False), flush=True)
    print("EXT109_QUARTERS", json.dumps(dict(q), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
