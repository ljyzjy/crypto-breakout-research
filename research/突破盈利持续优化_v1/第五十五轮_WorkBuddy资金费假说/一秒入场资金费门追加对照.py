"""Post-hoc application of the frozen gate to paired 1s/5s entry ledgers."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
FAST = H.parent / "第五十一轮_缩短市价入场延迟"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stats(frame, col, unknown):
    vals = frame[col].to_numpy(dtype=float)
    n, wins = len(vals), int((vals > 0).sum())
    neg = float(-vals[vals < 0].sum())
    return {"trades": n, "wins": wins, "win_rate_pct": 100 * wins / n if n else None,
            "mean_net_pct_notional": 100 * float(vals.mean()) if n else None,
            "profit_factor": float(vals[vals > 0].sum()) / neg if neg else None,
            "unknown_upper_count": unknown,
            "optimistic_win_rate_upper_pct": 100 * (wins + unknown) / (n + unknown) if n + unknown else None,
            "active_utc_days": len({pd.Timestamp(int(t), unit="ms", tz="UTC").date()
                                    for t in frame.one_second_entry_ts})}


def main():
    audit = json.loads((H / "资金费门独立核验.json").read_text(encoding="utf-8"))
    details_file = H / "已核验机会及资金费门.csv"
    assert audit["all_checks_pass"] and audit["detail_sha256"] == sha(details_file)
    gate = pd.read_csv(details_file, dtype={"year": str})
    assert not gate.duplicated(["year", "leverage", "observation_id"]).any()
    outputs, sources, detail_outputs = [], [H / "一秒入场补充检验方案.md", details_file, Path(__file__)] , []
    for year in ("2024", "2026"):
        folder = FAST / "2024中间批次_44候选" if year == "2024" else FAST
        pair_file = folder / f"{year}一秒五秒逐笔配对结果.parquet"
        comparison_file = folder / f"{year}一秒五秒配对对照.json"
        risk_file = (folder / "动态池单位收益与风险.parquet" if year == "2024" else
                     FAST / "2026一秒入场分批" / "动态池单位收益与风险.parquet")
        sources += [pair_file, comparison_file, risk_file]
        pairs = pd.read_parquet(pair_file)
        risk = pd.read_parquet(risk_file)
        refs = json.loads(comparison_file.read_text(encoding="utf-8"))["rows"]
        for lev in (10, 20):
            ref = next(r for r in refs if r["leverage"] == lev)
            part = pairs[pairs.leverage == lev].copy()
            one = risk[risk.variant.eq(f"one_second_2r_{lev}x")].set_index("observation_id")
            assert one.index.is_unique and len(part) == ref["paired_verified"]
            g = gate[(gate.year == year) & (gate.leverage == lev)]
            merged = part.merge(g, on=["observation_id", "leverage"], how="left", validate="one_to_one")
            assert len(merged) == len(part) and merged.allowed.notna().all()
            assert np.allclose(merged.five_second_net, merged.net_per_unit_notional, rtol=0, atol=1e-15)
            for item in merged.itertuples():
                r = one.loc[item.observation_id]
                assert r.risk_status == "verified" and not r.liq_proxy
                assert int(r.side) == int(item.side) and int(r.decision_ts) == int(item.decision_ts)
                assert int(r.entry_ts) == int(item.one_second_entry_ts)
                assert abs(float(r.net_per_unit_notional) - float(item.one_second_net)) < 1e-15
            u = int(ref["paired_unknown"])
            assert u == len(ref["unknown_ids"])
            filtered = merged[merged.allowed.eq(True)]
            before_one, before_five = stats(merged, "one_second_net", u), stats(merged, "five_second_net", u)
            for got, key in ((before_one, "one_second"), (before_five, "five_second")):
                expected = ref[key]
                assert got["trades"] == expected["trades"] and got["wins"] == expected["wins"]
                assert abs(got["mean_net_pct_notional"] - expected["mean_net_pct_notional"]) < 1e-10
                if expected["profit_factor"] is not None:
                    assert abs(got["profit_factor"] - expected["profit_factor"]) < 1e-10
            outputs.append({"year": year, "leverage": lev, "paired_unknown": u,
                "filtered_out_known": len(merged) - len(filtered), "baseline_one_second": before_one,
                "gate_one_second": stats(filtered, "one_second_net", u),
                "baseline_five_second": before_five,
                "gate_five_second": stats(filtered, "five_second_net", u)})
            detail_outputs.extend(merged[["year", "leverage", "observation_id", "side", "decision_ts",
                "allowed", "one_second_entry_ts", "one_second_net", "five_second_net"]].to_dict("records"))
    out = {"rows": outputs, "provenance_sha256": {str(p): sha(p) for p in sources},
           "note": "Post-hoc sensitivity; 2024 is incomplete, both periods previously studied, unknowns retained, unit opportunities only."}
    (H / "一秒入场资金费门追加对照.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(detail_outputs).to_csv(H / "一秒入场资金费门逐笔.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(outputs, ensure_ascii=False))


if __name__ == "__main__":
    main()
