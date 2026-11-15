"""Apply the already frozen BTC funding gate to complete 2024 tape groups."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
FAST = H.parent / "第五十一轮_缩短市价入场延迟"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stats(df, field, unknown):
    a = df[field].to_numpy(dtype=float)
    n, wins = len(a), int((a > 0).sum())
    loss = float(-a[a < 0].sum())
    return {"verified": n, "wins": wins, "win_rate_pct": 100 * wins / n if n else None,
            "mean_net_pct_notional": 100 * float(a.mean()) if n else None,
            "profit_factor": float(a[a > 0].sum()) / loss if loss else None,
            "unknown_events": unknown,
            "optimistic_win_rate_upper_pct": 100 * (wins + unknown) / (n + unknown) if n + unknown else None,
            "active_utc_days": len({pd.Timestamp(int(x), unit="ms", tz="UTC").date()
                                    for x in df.one_second_entry_ts})}


def main():
    proof = json.loads((H / "2024补齐账本隔离复核清单.json").read_text(encoding="utf-8"))
    assert proof["all_checks_pass"] and proof["output_sha256"] == sha(H / "2024补齐风险账本独立核验.json")
    for filename, expected in proof["input_sha256_before_after"].items():
        assert sha(Path(filename)) == expected
    gate_file = H / "已核验机会及资金费门.csv"
    gate_audit = json.loads((H / "资金费门独立核验.json").read_text(encoding="utf-8"))
    assert gate_audit["all_checks_pass"] and gate_audit["detail_sha256"] == sha(gate_file)
    quality_file = FAST / "2024一秒入场分批" / "动态池单位筛查完整性.json"
    quality = json.loads(quality_file.read_text(encoding="utf-8"))
    assert quality["complete"] and quality["verified_tape_paths"] == 93
    comp_file = FAST / "2024一秒五秒配对对照.json"
    pair_file = FAST / "2024一秒五秒逐笔配对结果.parquet"
    comp = json.loads(comp_file.read_text(encoding="utf-8"))["rows"]
    pairs = pd.read_parquet(pair_file)
    gate = pd.read_csv(gate_file, dtype={"year": str})
    rows, details = [], []
    for lev in (10, 20):
        ref = next(x for x in comp if x["leverage"] == lev)
        pair = pairs[pairs.leverage.eq(lev)].copy()
        g = gate[(gate.year.eq("2024")) & gate.leverage.eq(lev)]
        d = pair.merge(g, on=["observation_id", "leverage"], validate="one_to_one", how="left")
        assert len(d) == ref["paired_verified"] and d.allowed.notna().all()
        assert np.allclose(d.five_second_net, d.net_per_unit_notional, rtol=0, atol=1e-15)
        unknown = int(ref["paired_unknown"])
        baseline = stats(d, "one_second_net", unknown)
        assert baseline["verified"] == ref["one_second"]["trades"]
        assert baseline["wins"] == ref["one_second"]["wins"]
        assert abs(baseline["mean_net_pct_notional"] - ref["one_second"]["mean_net_pct_notional"]) < 1e-12
        filtered = d[d.allowed.eq(True)]
        rows.append({"year": "2024", "leverage": lev, "baseline_one_second": baseline,
                     "gate_one_second": stats(filtered, "one_second_net", unknown),
                     "known_filtered_out": len(d) - len(filtered)})
        details.extend(d[["year", "leverage", "observation_id", "side", "decision_ts", "allowed",
                          "one_second_entry_ts", "one_second_net", "five_second_net"]].to_dict("records"))
    sources = [H / "2024一秒补齐后的固定门复核方案.md", H / "2024补齐账本隔离复核清单.json",
               gate_file, quality_file, comp_file, pair_file, Path(__file__)]
    out = {"rows": rows, "provenance_sha256": {str(p): sha(p) for p in sources},
           "note": "47/47 archives; 16 original unknown candidates remain. Post-hoc historical unit opportunities, not an account."}
    (H / "2024补齐一秒资金费门复核.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(details).to_csv(H / "2024补齐一秒资金费门逐笔.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
