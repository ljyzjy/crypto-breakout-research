"""Post-hoc reuse of fixed exit slippage scenarios on the OI-qualified entries."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

H = Path(__file__).resolve().parent
P = H.parent
STRESS = P / "第五十九轮_退出滑点压力"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    gate_file, stress_file = H / "持仓量门逐笔机会.csv", STRESS / "退出滑点压力逐笔.csv"
    gate_audit = json.loads((H / "持仓量门独立核验.json").read_text(encoding="utf-8"))
    stress_audit = json.loads((STRESS / "退出滑点压力独立核验.json").read_text(encoding="utf-8"))
    assert gate_audit["all_checks_pass"] and gate_audit["detail_sha256"] == sha(gate_file)
    assert stress_audit["all_checks_pass"] and stress_audit["detail_sha256"] == sha(stress_file)
    with gate_file.open(encoding="utf-8-sig", newline="") as f:
        gates = {(r["year"], int(r["leverage"]), r["observation_id"]): r for r in csv.DictReader(f) if r["variant"] == "one_second"}
    with stress_file.open(encoding="utf-8-sig", newline="") as f:
        values = list(csv.DictReader(f))
    refs = json.loads((H / "持仓量门跨期对照.json").read_text(encoding="utf-8"))["rows"]
    grouped = defaultdict(list)
    for r in values:
        key = (r["year"], int(r["leverage"]), r["observation_id"])
        assert key in gates
        if math.isclose(float(r["exit_slip"]), 0.0005, abs_tol=1e-12):
            assert abs(float(r["net"]) - float(gates[key]["net"])) < 1e-14
        if gates[key]["gate"] == "True":
            grouped[(r["year"], int(r["leverage"]), r["exit_slip"])].append((r, gates[key]))
    output = []
    for year in ("2024", "2026"):
        for lev in (10, 20):
            ref = next(r for r in refs if r["year"] == year and r["leverage"] == lev and r["variant"] == "one_second")
            for slip in ("0.0005", "0.00075", "0.001"):
                group = grouped[(year, lev, slip)]
                values = [float(r["net"]) for r, _ in group]
                n, wins = len(values), sum(x > 0 for x in values)
                loss = -sum(x for x in values if x < 0)
                days = {datetime.fromtimestamp(int(g["entry_ts"]) / 1000, timezone.utc).date() for _, g in group}
                assert n == ref["oi_gate"]["verified_events"]
                result = {"year": year, "leverage": lev, "exit_slippage_pct": float(slip) * 100,
                    "verified_events": n, "wins": wins, "win_rate_pct": 100 * wins / n if n else None,
                    "mean_net_pct_notional": 100 * sum(values) / n if n else None,
                    "profit_factor": sum(x for x in values if x > 0) / loss if loss else None,
                    "active_utc_days": len(days), "unknown_upper_count": ref["oi_gate"]["unknown_upper_count"]}
                if slip == "0.0005":
                    assert wins == ref["oi_gate"]["wins"]
                    assert abs(result["mean_net_pct_notional"] - ref["oi_gate"]["mean_net_pct_notional"]) < 1e-12
                output.append(result)
    inputs = [H / "持仓量门退出滑点压力补充方案.md", gate_file, stress_file,
              H / "持仓量门独立核验.json", STRESS / "退出滑点压力独立核验.json", Path(__file__)]
    out = {"rows": output, "input_sha256": {str(p): sha(p) for p in inputs},
           "note": "Post-hoc fixed exit-price sensitivity; no entry or trigger re-simulation."}
    (H / "持仓量门退出滑点压力.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
