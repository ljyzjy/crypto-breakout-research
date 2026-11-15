"""Independent CSV aggregation and risk-ledger reconciliation for complete 2024."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import pandas as pd

H = Path(__file__).resolve().parent
FAST = H.parent / "第五十一轮_缩短市价入场延迟"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    with (H / "2024补齐一秒资金费门逐笔.csv").open(encoding="utf-8-sig", newline="") as f:
        details = list(csv.DictReader(f))
    result = json.loads((H / "2024补齐一秒资金费门复核.json").read_text(encoding="utf-8"))
    risk = pd.read_parquet(FAST / "2024一秒入场分批" / "动态池单位收益与风险.parquet")
    grouped = defaultdict(list)
    for row in details:
        grouped[int(row["leverage"])].append(row)
        variant = f'one_second_2r_{row["leverage"]}x'
        hit = risk[(risk.observation_id == row["observation_id"]) & (risk.variant == variant)]
        assert len(hit) == 1
        r = hit.iloc[0]
        assert r.risk_status == "verified" and not r.liq_proxy
        assert int(r.entry_ts) == int(row["one_second_entry_ts"])
        assert abs(float(r.net_per_unit_notional) - float(row["one_second_net"])) < 1e-15
    count = 0
    for result_row in result["rows"]:
        group = grouped[result_row["leverage"]]
        for key, subset in (("baseline_one_second", group),
                            ("gate_one_second", [r for r in group if r["allowed"] == "True"])):
            vals = [float(r["one_second_net"]) for r in subset]
            ref = result_row[key]
            assert ref["verified"] == len(vals) and ref["wins"] == sum(v > 0 for v in vals)
            assert abs(ref["mean_net_pct_notional"] - 100 * sum(vals) / len(vals)) < 1e-12
            loss = -sum(v for v in vals if v < 0)
            assert abs(ref["profit_factor"] - sum(v for v in vals if v > 0) / loss) < 1e-12
            days = {datetime.fromtimestamp(int(r["one_second_entry_ts"]) / 1000, timezone.utc).date() for r in subset}
            assert ref["active_utc_days"] == len(days) and ref["unknown_events"] == 16
            count += 1
    out = {"all_checks_pass": True, "opportunity_paths_checked": len(details),
           "aggregate_groups_checked": count,
           "result_sha256": sha(H / "2024补齐一秒资金费门复核.json"),
           "detail_sha256": sha(H / "2024补齐一秒资金费门逐笔.csv"),
           "risk_audit_sha256": sha(H / "2024补齐账本隔离复核清单.json"),
           "audit_sha256": sha(Path(__file__))}
    (H / "2024补齐一秒资金费门独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
