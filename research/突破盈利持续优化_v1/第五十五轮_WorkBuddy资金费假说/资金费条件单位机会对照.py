"""Frozen exploratory BTC funding gate applied to previously verified unit ledgers."""
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
PREV = P / "第四十七轮_一次重新突破确认"
REFERENCE = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp\fnd_BTCUSDT.parquet")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def funding_daily(frame):
    df = frame.copy()
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    df["day"] = df.dt.dt.floor("D")
    df["offset_sec"] = (df.dt - df.dt.dt.floor("h")).dt.total_seconds()
    def reduce_day(x):
        valid = (len(x) == 3 and x.dt.nunique() == 3
                 and set(x.dt.dt.hour) == {0, 8, 16}
                 and x.funding_interval_hours.eq(8).all()
                 and x.last_funding_rate.notna().all()
                 and np.isfinite(x.last_funding_rate).all()
                 and (x.offset_sec >= 0).all() and (x.offset_sec < 60).all())
        return pd.Series({"valid": valid,
                          "rate": float(x.last_funding_rate.sum()) if valid else np.nan})
    daily = df.groupby("day").apply(reduce_day, include_groups=False)
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"))
    daily["rate"] = pd.to_numeric(daily.rate, errors="coerce")
    daily["threshold"] = daily.rate.rolling(365, min_periods=365).quantile(0.40)
    return daily


def gate_for(decision_ts, daily):
    decision = pd.Timestamp(int(decision_ts), unit="ms", tz="UTC")
    prior = decision.floor("D") - pd.Timedelta(days=1)
    if prior not in daily.index:
        return None, prior, None, None
    item = daily.loc[prior]
    if pd.isna(item.rate) or pd.isna(item.threshold):
        return None, prior, None, None
    return bool(item.rate > item.threshold), prior, float(item.rate), float(item.threshold)


def choose(side, gate):
    assert side in (-1, 1)
    return True if side == 1 else gate


def test_causality():
    days = pd.date_range("2020-01-01", periods=400, freq="D", tz="UTC")
    rows = [{"dt": day + pd.Timedelta(hours=hour), "funding_interval_hours": 8,
             "last_funding_rate": (i + 1) / 1e8}
            for i, day in enumerate(days) for hour in (0, 8, 16)]
    sample = pd.DataFrame(rows)
    t = days[390]
    ts = int(t.value // 1_000_000)
    original = gate_for(ts, funding_daily(sample))
    assert original[0] is True and original[1] == days[389]
    assert gate_for(ts + 86_399_000, funding_daily(sample)) == original
    future = sample.copy()
    future.loc[future.dt >= t, "last_funding_rate"] = -1000.0
    assert gate_for(ts, funding_daily(future)) == original
    missing_day = sample[sample.dt.dt.floor("D") != days[250]]
    assert gate_for(ts, funding_daily(missing_day))[0] is None
    missing_settlement = sample[sample.dt != days[250] + pd.Timedelta(hours=8)]
    assert gate_for(ts, funding_daily(missing_settlement))[0] is None
    duplicated = pd.concat([sample, sample[sample.dt == days[250]]], ignore_index=True)
    assert gate_for(ts, funding_daily(duplicated))[0] is None
    assert choose(1, None) is True and choose(-1, None) is None
    assert choose(-1, True) is True and choose(-1, False) is False
    return {"all_checks_pass": True, "checks": ["last completed UTC day",
        "within-day consistency", "future perturbation", "missing whole day",
        "missing settlement", "duplicate settlement", "short-only filter"]}


def metrics(rows, unknown):
    vals = np.array([float(r["net_per_unit_notional"]) for r in rows], dtype=float)
    n = len(vals)
    wins = int((vals > 0).sum())
    plus, minus = float(vals[vals > 0].sum()), float(-vals[vals < 0].sum())
    dates = {pd.Timestamp(int(r["entry_ts"]), unit="ms", tz="UTC").strftime("%Y-%m-%d")
             for r in rows}
    return {"verified_events": n, "verified_wins": wins,
            "verified_win_rate_pct": 100 * wins / n if n else None,
            "mean_net_pct_notional": 100 * float(vals.mean()) if n else None,
            "profit_factor": plus / minus if minus else None,
            "active_utc_days": len(dates), "unknown_events_upper_count": unknown,
            "optimistic_win_rate_upper_pct": 100 * (wins + unknown) / (n + unknown)
            if n + unknown else None}


def main():
    tests = test_causality()
    audit_path = H / "参考资金费来源与完整性核验.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["source_sha256"] == digest(REFERENCE)
    daily = funding_daily(pd.read_parquet(REFERENCE))
    compare_path = PREV / "单次重试跨期单位对照.json"
    comparison = json.loads(compare_path.read_text(encoding="utf-8"))["rows"]
    outputs, details = [], []
    source_paths = [H / "冻结研究方案.md", H / "参考资金费校验.py", audit_path,
                    Path(__file__), REFERENCE, compare_path]
    for year in ("2023", "2024", "2026"):
        folder = PREV / ("2023冻结输入" if year == "2023" else "跨期冻结输入")
        led_name = "baseline_ledger.parquet" if year == "2023" else f"{year}_ledger.parquet"
        baseline_file = folder / led_name
        retry_dir = PREV / f"{year}重试分批"
        retry_signal_file = retry_dir / "动态池逐笔信号筛查.parquet"
        retry_file = retry_dir / "动态池单位收益与风险.parquet"
        source_paths += [baseline_file, retry_signal_file, retry_file]
        baseline = pd.read_parquet(baseline_file)
        retry = pd.read_parquet(retry_file)
        retry_ids = set(pd.read_parquet(retry_signal_file).observation_id)
        for lev in (10, 20):
            ref = next(x for x in comparison if x["year"] == year
                       and x["leverage"] == lev and x["strategy"] == "single_retest")
            variant = f"normal_2r_{lev}x"
            old = baseline[baseline.variant.eq(variant)]
            new = retry[retry.variant.eq(variant)]
            assert old.observation_id.is_unique and new.observation_id.is_unique
            old = old.set_index("observation_id")
            new = new.set_index("observation_id")
            known, kept, removed = [], [], []
            gate_unknown = 0
            for obs in ref["verified_observation_ids"]:
                frame = new if obs in retry_ids else old
                assert obs in frame.index, (year, lev, obs)
                record = frame.loc[obs].to_dict()
                record["observation_id"] = obs
                assert record["status"] == "verified" and record["risk_status"] == "verified"
                assert not record["liq_proxy"] and math.isfinite(float(record["net_per_unit_notional"]))
                assert int(record["entry_ts"]) >= int(record["decision_ts"]) + 10_000
                side = int(record["side"])
                gate, day, rate, threshold = gate_for(record["decision_ts"], daily)
                allowed = choose(side, gate)
                known.append(record)
                if allowed is True:
                    kept.append(record)
                elif allowed is False:
                    removed.append(record)
                else:
                    gate_unknown += 1
                details.append({"year": year, "leverage": lev, "observation_id": obs,
                    "side": side, "decision_ts": int(record["decision_ts"]),
                    "entry_ts": int(record["entry_ts"]), "funding_last_utc_day": str(day),
                    "funding_daily_sum": rate, "funding_quantile_40": threshold,
                    "short_gate": gate, "allowed": allowed,
                    "net_per_unit_notional": float(record["net_per_unit_notional"])})
            original_unknown = int(ref["possible_unknown_events"])
            assert original_unknown == len(ref["unknown_observation_ids"])
            base = metrics(known, original_unknown)
            assert base["verified_events"] == ref["verified_events"]
            assert base["verified_wins"] == ref["verified_wins"]
            assert abs(base["mean_net_pct_notional"] - ref["mean_net_pct_notional"]) < 1e-10
            assert len(known) == len(kept) + len(removed) + gate_unknown
            outputs.append({"year": year, "leverage": lev, "baseline": base,
                "funding_short_gate": metrics(kept, original_unknown + gate_unknown),
                "known_filtered_out": metrics(removed, 0),
                "unknown_from_original": original_unknown,
                "additional_unknown_funding_gate": gate_unknown})
    manifest = {str(p): digest(p) for p in source_paths}
    result = {"plan_sha256": digest(H / "冻结研究方案.md"), "causality_tests": tests,
        "provenance_sha256": manifest, "rows": outputs,
        "note": "Exploratory historical unit opportunities only; prior project inspected these periods. Unknowns are not filled; no shared-account outcome is computed."}
    (H / "资金费条件单位机会对照.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(details).to_csv(H / "已核验机会及资金费门.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(outputs, ensure_ascii=False))


if __name__ == "__main__":
    main()
