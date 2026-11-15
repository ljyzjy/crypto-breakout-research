"""Independently re-summarize post-hoc one-second results and source pairings."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json

import pandas as pd

H = Path(__file__).resolve().parent
FAST = H.parent / "第五十一轮_缩短市价入场延迟"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with (H / "一秒入场资金费门逐笔.csv").open(encoding="utf-8-sig", newline="") as f:
        detail = list(csv.DictReader(f))
    with (H / "已核验机会及资金费门.csv").open(encoding="utf-8-sig", newline="") as f:
        prior = {(r["year"], r["leverage"], r["observation_id"]): r for r in csv.DictReader(f)}
    result = json.loads((H / "一秒入场资金费门追加对照.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for row in detail:
        key = row["year"], row["leverage"], row["observation_id"]
        source = prior[key]
        assert source["allowed"] == row["allowed"] and source["side"] == row["side"]
        assert source["decision_ts"] == row["decision_ts"]
        assert abs(float(source["net_per_unit_notional"]) - float(row["five_second_net"])) < 1e-15
        groups[(row["year"], int(row["leverage"]))].append(row)
    n_stats = 0
    for row in result["rows"]:
        all_rows = groups[(row["year"], row["leverage"])]
        yes = [r for r in all_rows if r["allowed"] == "True"]
        assert len(all_rows) - len(yes) == row["filtered_out_known"]
        for name, items, field in (("baseline_one_second", all_rows, "one_second_net"),
                                    ("gate_one_second", yes, "one_second_net"),
                                    ("baseline_five_second", all_rows, "five_second_net"),
                                    ("gate_five_second", yes, "five_second_net")):
            values = [float(r[field]) for r in items]
            expected = row[name]
            assert expected["trades"] == len(values)
            assert expected["wins"] == sum(v > 0 for v in values)
            assert abs(expected["mean_net_pct_notional"] - 100 * sum(values) / len(values)) < 1e-12
            losses = -sum(v for v in values if v < 0)
            if losses:
                assert abs(expected["profit_factor"] - sum(v for v in values if v > 0) / losses) < 1e-12
            days = {datetime.fromtimestamp(int(r["one_second_entry_ts"]) / 1000, timezone.utc).date() for r in items}
            assert len(days) == expected["active_utc_days"]
            assert expected["unknown_upper_count"] == row["paired_unknown"]
            n_stats += 1
    # The immutable paired file supplies both alternative realized paths.
    for year in ("2024", "2026"):
        folder = FAST / "2024中间批次_44候选" if year == "2024" else FAST
        pair = pd.read_parquet(folder / f"{year}一秒五秒逐笔配对结果.parquet")
        keyed = {(str(r.observation_id), int(r.leverage)): r for r in pair.itertuples()}
        for r in (item for item in detail if item["year"] == year):
            source = keyed[(r["observation_id"], int(r["leverage"]))]
            assert abs(float(source.one_second_net) - float(r["one_second_net"])) < 1e-15
            assert abs(float(source.five_second_net) - float(r["five_second_net"])) < 1e-15
            assert int(source.one_second_entry_ts) == int(r["one_second_entry_ts"])
    out = {"all_checks_pass": True, "paired_records_checked": len(detail),
           "aggregate_groups_checked": n_stats,
           "output_sha256": sha(H / "一秒入场资金费门追加对照.json"),
           "detail_sha256": sha(H / "一秒入场资金费门逐笔.csv"),
           "audit_sha256": sha(Path(__file__))}
    (H / "一秒追加独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
