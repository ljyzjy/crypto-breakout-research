"""Compare trailing and previous exits on identical verified historical entries."""
from datetime import datetime, timezone
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path

import pandas as pd
import replay_cross as replay

H, P = replay.H, replay.P
R106 = P / "第一百零六轮_一秒五秒分层入场"
spec = importlib.util.spec_from_file_location("ext113_oldstages", R106 / "run_staged.py")
oldstages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oldstages)


def metric(paths, slip):
    values = []
    for p in paths:
        side, entry, raw = D(int(p["side"])), D(str(p["entry_fill"])), D(str(p["exit_raw"]))
        fill = raw * (1 - side * slip)
        values.append(side * (fill - entry) / entry - D(".0005") * (1 + fill / entry) - D(str(p["funding"])))
    profit = sum((v for v in values if v > 0), D(0))
    loss = -sum((v for v in values if v < 0), D(0))
    return {"trades": len(values), "wins": sum(v > 0 for v in values),
            "win_rate_pct": float(D(100) * sum(v > 0 for v in values) / len(values)) if values else None,
            "mean_net_pct_notional": float(D(100) * sum(values, D(0)) / len(values)) if values else None,
            "profit_factor": float(profit / loss) if loss else None,
            "active_utc_days": len({datetime.fromtimestamp(int(x["entry_ts"]) / 1000, timezone.utc).date() for x in paths})}


def main():
    replay.bulk.runner.guard(start=True)
    old_summary = json.loads((R106 / "分层入场单位结果.json").read_text(encoding="utf-8"))
    old_proof = json.loads((R106 / "分层入场独立核验.json").read_text(encoding="utf-8"))
    assert old_proof["all_checks_pass"] and old_proof["result_sha256"] == replay.bulk.sha(R106 / "分层入场单位结果.json")
    summaries, details, provenance = [], [], {}
    for year in ("2024", "2026"):
        paths_file = H / f"{year}跟踪退出风险账本.json"
        data = json.loads(paths_file.read_text(encoding="utf-8"))
        risk = json.loads((H / f"{year}跟踪退出风险独立核验.json").read_text(encoding="utf-8"))
        tape = json.loads((H / f"{year}跟踪退出逐笔独立样本核验.json").read_text(encoding="utf-8"))
        assert risk["all_checks_pass"] and risk["ledger_sha256"] == replay.bulk.sha(paths_file)
        assert risk["audit_code_sha256"] == replay.bulk.sha(H / "audit_cross_risk.py")
        assert tape["all_checks_pass"] and tape["replay_fingerprint"] == data["replay_fingerprint"]
        assert tape["audit_code_sha256"] == replay.bulk.sha(H / "audit_cross_tape.py")
        assert tape["logic_sha256"] == replay.bulk.sha(replay.R112 / "audit_trailing_logic.py")
        provenance[year] = {"ledger_sha256": replay.bulk.sha(paths_file),
                            "risk_audit_sha256": replay.bulk.sha(H / f"{year}跟踪退出风险独立核验.json"),
                            "tape_audit_sha256": replay.bulk.sha(H / f"{year}跟踪退出逐笔独立样本核验.json")}
        _, _, early_map, _, one_map, _, _ = oldstages.load_year(year)
        trailing_map = {(x["observation_id"], x["variant"]): x for x in data["records"]}
        for lev in (10, 20):
            variant = f"one_observation_2r_{lev}x"
            original = {k[0]: v for k, v in early_map.items() if k[1] == variant and v.get("status") == "verified"
                        and v.get("risk_status") == "verified" and not pd.isna(v.get("liq_proxy")) and not bool(v["liq_proxy"])}
            pairs = []
            for obs, base in original.items():
                trailing = trailing_map.get((obs, variant))
                one = one_map.get((obs, variant.replace("_2r_", "_1r_")))
                if not trailing or not one or any(x.get("status") != "verified" or x.get("risk_status") != "verified"
                    or pd.isna(x.get("liq_proxy")) or bool(x["liq_proxy"]) for x in (trailing, one)):
                    continue
                assert all(int(x["entry_ts"]) == int(base["entry_ts"]) for x in (trailing, one))
                assert all(abs(D(str(x["entry_fill"])) - D(str(base["entry_fill"]))) < D("1e-9") for x in (trailing, one))
                pairs.append((base, one, trailing))
                details.append({"year": year, "leverage": lev, "observation_id": obs, "entry_ts": int(base["entry_ts"]),
                                "trailing_action": trailing["trailing_action"], "original_net": str(base["net_per_unit_notional"]),
                                "one_r_net": str(one["net_per_unit_notional"]), "trailing_net": str(trailing["net_per_unit_notional"])})
            ref = next(x for x in old_summary["rows"] if x["year"] == year and x["leverage"] == lev
                       and x["policy"] == "early_2r" and x["exit_slippage_pct"] == .05)
            assert len(original) == ref["trades"]
            for idx, rule in ((0, "original_2r"), (1, "one_r"), (2, "trailing")):
                for slip in (D(".0005"), D(".00075"), D(".001")):
                    summaries.append({"year": year, "leverage": lev, "rule": rule, "exit_slippage_pct": float(100 * slip),
                                      **metric([p[idx] for p in pairs], slip), "original_unknown": ref["unknown"],
                                      "additional_pair_unknown": len(original) - len(pairs)})
    detail_path = H / "跨期跟踪退出配对明细.csv"
    pd.DataFrame(details).to_csv(detail_path, index=False, encoding="utf-8")
    out = {"rows": summaries, "sources": provenance, "detail_sha256": replay.bulk.sha(detail_path), "code_sha256": replay.bulk.sha(Path(__file__)),
           "frozen_sha256": replay.bulk.sha(H / "输入冻结.json"), "note": "Historical unit paths; not independent blind data or wallet returns."}
    (H / "跨期跟踪退出配对结果.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT113_SUMMARY", json.dumps(summaries, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
