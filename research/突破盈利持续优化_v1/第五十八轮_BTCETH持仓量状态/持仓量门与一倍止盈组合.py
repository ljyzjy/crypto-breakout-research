"""Post-hoc fixed OI gate on audited same-entry 1R versus 2R paths."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
R48 = H.parent / "第四十八轮_固定一倍风险止盈"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stats(d, field, unknown):
    v = d[field].to_numpy(dtype=float)
    n, wins = len(v), int((v > 0).sum())
    loss = float(-v[v < 0].sum())
    return {"verified_events": n, "wins": wins, "win_rate_pct": 100 * wins / n if n else None,
        "mean_net_pct_notional": 100 * float(v.mean()) if n else None,
        "profit_factor": float(v[v > 0].sum()) / loss if loss else None,
        "worst_net_pct_notional": 100 * float(v.min()) if n else None,
        "active_utc_days": len({datetime.fromtimestamp(int(t) / 1000, timezone.utc).date() for t in d.entry_ts}),
        "unknown_upper_count": unknown,
        "optimistic_win_rate_upper_pct": 100 * (wins + unknown) / (n + unknown) if n + unknown else None}


def main():
    dfile = H / "持仓量门逐笔机会.csv"
    audit = json.loads((H / "持仓量门独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["detail_sha256"] == sha(dfile)
    gate = pd.read_csv(dfile, dtype={"year": str})
    inputs = [H / "持仓量门与一倍止盈组合方案.md", dfile, H / "持仓量门独立核验.json", Path(__file__)]
    out, details = [], []
    for year in ("2023", "2024", "2026"):
        pair_file = R48 / f"{year}一倍两倍逐笔配对结果.parquet"
        compare_file = R48 / f"{year}一倍两倍配对对照.json"
        ledger_audit_file = R48 / f"{year}一倍止盈账本独立核验.json"
        sample_audit_file = R48 / f"{year}一倍止盈逐笔独立抽查.json"
        inputs += [pair_file, compare_file, ledger_audit_file, sample_audit_file]
        assert json.loads(ledger_audit_file.read_text(encoding="utf-8"))["all_checks_pass"]
        assert json.loads(sample_audit_file.read_text(encoding="utf-8"))["all_checks_pass"]
        pairs = pd.read_parquet(pair_file)
        comp = json.loads(compare_file.read_text(encoding="utf-8"))["rows"]
        for lev in (10, 20):
            reference = next(r for r in comp if r["leverage"] == lev)
            frame = pairs[pairs.leverage.eq(lev)]
            subset = gate[gate.year.eq(year) & gate.leverage.eq(lev) & gate.variant.eq("five_second")]
            merged = frame.merge(subset, on=["observation_id", "leverage"], how="left", validate="one_to_one")
            assert len(merged) == reference["paired_verified"] and not merged.decision_ts.isna().any()
            assert np.allclose(merged.two_r_net, merged.net, rtol=0, atol=1e-15)
            u = int(reference["paired_unknown"])
            n_unknown = int(merged.gate.isna().sum())
            selected = merged[merged.gate.eq(True)]
            one, two = stats(selected, "one_r_net", u + n_unknown), stats(selected, "two_r_net", u + n_unknown)
            base1, base2 = stats(merged, "one_r_net", u), stats(merged, "two_r_net", u)
            for base, name in ((base1, "one_r"), (base2, "two_r")):
                assert base["verified_events"] == reference[name]["trades"] and base["wins"] == reference[name]["wins"]
                assert abs(base["mean_net_pct_notional"] - reference[name]["mean_net_pct_notional"]) < 1e-10
            diff = selected.one_r_net.to_numpy(dtype=float) - selected.two_r_net.to_numpy(dtype=float)
            out.append({"year": year, "leverage": lev, "oi_gate_1r": one, "oi_gate_2r": two,
                "one_r_better": int((diff > 1e-12).sum()), "one_r_worse": int((diff < -1e-12).sum()),
                "same": int((np.abs(diff) <= 1e-12).sum()), "original_unknown": u,
                "additional_feature_unknown": n_unknown})
            details.extend(merged[["year", "leverage", "observation_id", "side", "decision_ts", "entry_ts",
                                   "gate", "one_r_net", "two_r_net"]].to_dict("records"))
    detail_file = H / "持仓量门与一倍止盈逐笔.csv"
    pd.DataFrame(details).to_csv(detail_file, index=False, encoding="utf-8-sig")
    result = {"rows": out, "detail_sha256": sha(detail_file), "input_sha256": {str(p): sha(p) for p in inputs},
              "note": "Post-hoc combination, same entries, costed unit outcomes, not blind or account performance."}
    (H / "持仓量门与一倍止盈组合.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
