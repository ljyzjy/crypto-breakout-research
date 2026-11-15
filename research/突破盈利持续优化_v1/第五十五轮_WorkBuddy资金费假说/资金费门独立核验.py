"""Independent reconstruction using Decimal and reference monthly CSVs."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import json
import math

import pandas as pd

H = Path(__file__).resolve().parent
REF = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp")
PREV = H.parent / "第四十七轮_一次重新突破确认"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = []
    files = sorted(REF.glob("BTCUSDT-fundingRate-????-??.csv"))
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                source.append((int(row["calc_time"]), int(row["funding_interval_hours"]),
                               Decimal(row["last_funding_rate"])))
    source.sort()
    parquet = pd.read_parquet(REF / "fnd_BTCUSDT.parquet").sort_values("dt")
    assert len(source) == len(parquet)
    for (ms, interval, rate), p in zip(source, parquet.itertuples(index=False)):
        assert ms == int(p.dt.value // 1_000_000) and interval == p.funding_interval_hours
        assert abs(float(rate) - float(p.last_funding_rate)) < 1e-15
    by_day = defaultdict(list)
    for ms, interval, rate in source:
        dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
        by_day[dt.date()].append((dt.hour, dt.minute, dt.second, interval, rate))
    daily = {}
    for day, data in by_day.items():
        assert len(data) == 3 and {x[0] for x in data} == {0, 8, 16}
        assert all(x[1] == x[2] == 0 and x[3] == 8 for x in data)
        daily[day] = sum((x[4] for x in data), Decimal(0))

    with (H / "已核验机会及资金费门.csv").open(encoding="utf-8-sig", newline="") as f:
        details = list(csv.DictReader(f))
    result = json.loads((H / "资金费条件单位机会对照.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for row in details:
        dt = datetime.fromtimestamp(int(row["decision_ts"]) / 1000, timezone.utc)
        prev = dt.date() - timedelta(days=1)
        window = [daily[prev - timedelta(days=i)] for i in range(365)]
        ranked = sorted(window)
        # Linear interpolation of the fixed 0.40 quantile of 365 observations.
        threshold = ranked[145] + Decimal("0.6") * (ranked[146] - ranked[145])
        gate = daily[prev] > threshold
        assert abs(float(daily[prev]) - float(row["funding_daily_sum"])) < 1e-15
        assert abs(float(threshold) - float(row["funding_quantile_40"])) < 1e-15
        assert (row["short_gate"] == "True") == gate
        allow = int(row["side"]) == 1 or gate
        assert (row["allowed"] == "True") == allow
        groups[(row["year"], int(row["leverage"]))].append(row)
    checks = 0
    for entry in result["rows"]:
        key = (entry["year"], entry["leverage"])
        rows = groups[key]
        for name, subset in (("baseline", rows),
                             ("funding_short_gate", [r for r in rows if r["allowed"] == "True"]),
                             ("known_filtered_out", [r for r in rows if r["allowed"] == "False"])):
            values = [float(r["net_per_unit_notional"]) for r in subset]
            expected = entry[name]
            assert len(values) == expected["verified_events"]
            assert sum(v > 0 for v in values) == expected["verified_wins"]
            if values:
                assert abs(sum(values) / len(values) * 100 - expected["mean_net_pct_notional"]) < 1e-12
            neg = -sum(v for v in values if v < 0)
            if neg:
                assert abs(sum(v for v in values if v > 0) / neg - expected["profit_factor"]) < 1e-12
            days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in subset}
            assert len(days) == expected["active_utc_days"]
            checks += 1

    # Independently verify every reported opportunity against its original risk ledger.
    for year in ("2023", "2024", "2026"):
        folder = PREV / ("2023冻结输入" if year == "2023" else "跨期冻结输入")
        name = "baseline_ledger.parquet" if year == "2023" else f"{year}_ledger.parquet"
        old = pd.read_parquet(folder / name)
        retry_folder = PREV / f"{year}重试分批"
        new = pd.read_parquet(retry_folder / "动态池单位收益与风险.parquet")
        retry_ids = set(pd.read_parquet(retry_folder / "动态池逐笔信号筛查.parquet").observation_id)
        for row in [r for r in details if r["year"] == year]:
            ledger = new if row["observation_id"] in retry_ids else old
            match = ledger[(ledger.observation_id == row["observation_id"]) &
                           (ledger.variant == f'normal_2r_{row["leverage"]}x')]
            assert len(match) == 1
            item = match.iloc[0]
            assert item.risk_status == "verified" and not item.liq_proxy
            assert int(item.side) == int(row["side"])
            assert int(item.decision_ts) == int(row["decision_ts"])
            assert int(item.entry_ts) == int(row["entry_ts"])
            assert abs(float(item.net_per_unit_notional) - float(row["net_per_unit_notional"])) < 1e-15

    report = {"all_checks_pass": True, "csv_months": len(files),
              "local_csv_vs_parquet_records": len(source),
              "opportunity_rows_independently_checked": len(details),
              "aggregate_groups_checked": checks,
              "detail_sha256": sha(H / "已核验机会及资金费门.csv"),
              "result_sha256": sha(H / "资金费条件单位机会对照.json"),
              "audit_script_sha256": sha(Path(__file__)),
              "scope": "All local monthly CSV numeric rows versus local parquet; only three months independently matched official archives in the source audit."}
    (H / "资金费门独立核验.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
