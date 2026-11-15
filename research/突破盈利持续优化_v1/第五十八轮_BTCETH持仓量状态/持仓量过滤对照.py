"""One predeclared BTC/ETH OI state gate on previously audited unit trades."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
F55 = P / "第五十五轮_WorkBuddy资金费假说"
R47 = P / "第四十七轮_一次重新突破确认"
R51 = P / "第五十一轮_缩短市价入场延迟"
M, SLOT = 60_000, 300_000


def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def feature(decision, source):
    now = ((int(decision) - 15 * M) // SLOT) * SLOT
    past = now - 60 * M
    if not (15 * M <= int(decision) - now < 20 * M):
        raise AssertionError("invalid feature time")
    vals = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        a, b = source.get((sym, now), []), source.get((sym, past), [])
        if len(a) != 1 or len(b) != 1:
            return None, now, {}, "missing_or_duplicate"
        if any(v is None or not math.isfinite(v) or v <= 0 for v in (a[0], b[0])):
            return None, now, {}, "invalid_oi"
        vals[sym] = a[0] / b[0] - 1.0
    return all(v > 0 for v in vals.values()), now, vals, "verified"


def test_feature():
    t = 1_704_067_200_000 + 15 * M
    now = ((t - 15 * M) // SLOT) * SLOT
    data = {(sym, ts): [v] for sym, new, old in (("BTCUSDT", 101.0, 100.0),
            ("ETHUSDT", 201.0, 200.0)) for ts, v in ((now, new), (now - 60 * M, old))}
    result = feature(t, data)
    assert result[0] is True and result[1] == now
    future = dict(data)
    future[("BTCUSDT", now + SLOT)] = [-999.0]
    assert feature(t, future) == result
    equal = dict(data); equal[("BTCUSDT", now)] = [100.0]
    assert feature(t, equal)[0] is False
    falling = dict(data); falling[("ETHUSDT", now)] = [199.0]
    assert feature(t, falling)[0] is False
    missing = dict(data); missing.pop(("BTCUSDT", now - 60 * M))
    assert feature(t, missing)[0] is None
    duplicate = dict(data); duplicate[("ETHUSDT", now)] = [201.0, 201.0]
    assert feature(t, duplicate)[0] is None
    zero = dict(data); zero[("ETHUSDT", now - 60 * M)] = [0.0]
    assert feature(t, zero)[0] is None
    before = feature(t - 1, data)
    assert before[0] is None and before[1] == now - SLOT
    return {"all_checks_pass": True, "checks": ["future perturbation", "strict increase", "two-asset conjunction",
        "missing", "duplicate", "zero", "5-minute boundary", "15-minute embargo"]}


def metrics(rows, unknown):
    vals = np.asarray([float(r["net"]) for r in rows], float)
    n, wins = len(vals), int((vals > 0).sum())
    neg = float(-vals[vals < 0].sum())
    days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in rows}
    return {"verified_events": n, "wins": wins, "win_rate_pct": 100 * wins / n if n else None,
        "mean_net_pct_notional": 100 * float(vals.mean()) if n else None,
        "profit_factor": float(vals[vals > 0].sum()) / neg if neg else None,
        "worst_net_pct_notional": 100 * float(vals.min()) if n else None,
        "active_utc_days": len(days), "unknown_upper_count": unknown,
        "optimistic_win_rate_upper_pct": 100 * (wins + unknown) / (n + unknown) if n + unknown else None}


def main():
    src = H / "持仓量来源与质量核验.json"
    qa = json.loads(src.read_text(encoding="utf-8"))
    points = H / "持仓量所需时间点.json"
    assert qa["all_official_samples_pass"] and qa["causality_tests"]["all_checks_pass"]
    assert qa["selected_keys_sha256"] == digest(points)
    assert qa["plan_sha256"] == digest(H / "冻结研究方案.md")
    detail_file = F55 / "已核验机会及资金费门.csv"
    previous_audit = json.loads((F55 / "资金费门独立核验.json").read_text(encoding="utf-8"))
    assert previous_audit["all_checks_pass"] and previous_audit["detail_sha256"] == digest(detail_file)
    source = {(r["symbol"], int(r["ts"])): r["values"] for r in json.loads(points.read_text(encoding="utf-8"))}
    signal = pd.read_csv(detail_file, dtype={"year": str})
    assert not signal.duplicated(["year", "leverage", "observation_id"]).any()
    old = json.loads((R47 / "单次重试跨期单位对照.json").read_text(encoding="utf-8"))["rows"]
    rows, all_detail = [], []
    five_hash = digest(R47 / "单次重试跨期单位对照.json")
    for year in ("2023", "2024", "2026"):
        for lev in (10, 20):
            frame = signal[signal.year.eq(year) & signal.leverage.eq(lev)]
            ref = next(r for r in old if r["year"] == year and r["leverage"] == lev and r["strategy"] == "single_retest")
            assert set(frame.observation_id) == set(ref["verified_observation_ids"])
            results = []
            for r in frame.itertuples(index=False):
                allow, t0, rates, status = feature(r.decision_ts, source)
                results.append({"year": year, "leverage": lev, "variant": "five_second",
                    "observation_id": r.observation_id, "side": int(r.side), "decision_ts": int(r.decision_ts),
                    "entry_ts": int(r.entry_ts), "net": float(r.net_per_unit_notional),
                    "feature_ts": t0, "btc_oi_change": rates.get("BTCUSDT"),
                    "eth_oi_change": rates.get("ETHUSDT"), "gate": allow, "feature_status": status})
            original_unknown = int(ref["possible_unknown_events"])
            base = metrics(results, original_unknown)
            assert base["verified_events"] == ref["verified_events"] and base["wins"] == ref["verified_wins"]
            assert abs(base["mean_net_pct_notional"] - ref["mean_net_pct_notional"]) < 1e-10
            valid = [r for r in results if r["gate"] is True]
            removed = [r for r in results if r["gate"] is False]
            unknown = [r for r in results if r["gate"] is None]
            assert len(results) == len(valid) + len(removed) + len(unknown)
            rows.append({"year": year, "leverage": lev, "variant": "five_second",
                "baseline": base, "oi_gate": metrics(valid, original_unknown + len(unknown)),
                "known_filtered": metrics(removed, 0), "original_unknown": original_unknown,
                "additional_feature_unknown": len(unknown)})
            all_detail.extend(results)
    for year in ("2024", "2026"):
        pair_file, comp_file = R51 / f"{year}一秒五秒逐笔配对结果.parquet", R51 / f"{year}一秒五秒配对对照.json"
        if year == "2024":
            proof = json.loads((F55 / "2024补齐账本隔离复核清单.json").read_text(encoding="utf-8"))
            assert proof["all_checks_pass"] and proof["input_sha256_before_after"][str(pair_file)] == digest(pair_file)
            assert proof["input_sha256_before_after"][str(comp_file)] == digest(comp_file)
        else:
            proof = json.loads((F55 / "一秒入场资金费门追加对照.json").read_text(encoding="utf-8"))
            assert proof["provenance_sha256"][str(pair_file)] == digest(pair_file)
            assert proof["provenance_sha256"][str(comp_file)] == digest(comp_file)
            assert json.loads((F55 / "一秒追加独立核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
        pair = pd.read_parquet(pair_file)
        comparisons = json.loads(comp_file.read_text(encoding="utf-8"))["rows"]
        for lev in (10, 20):
            ref = next(r for r in comparisons if r["leverage"] == lev)
            part = pair[pair.leverage.eq(lev)]
            valid_signal = signal[signal.year.eq(year) & signal.leverage.eq(lev)]
            merged = part.merge(valid_signal, on=["observation_id", "leverage"], how="left", validate="one_to_one")
            assert len(merged) == ref["paired_verified"] and not merged.decision_ts.isna().any()
            assert np.allclose(merged.five_second_net, merged.net_per_unit_notional, rtol=0, atol=1e-15)
            results = []
            for r in merged.itertuples(index=False):
                allow, t0, rates, status = feature(r.decision_ts, source)
                results.append({"year": year, "leverage": lev, "variant": "one_second",
                    "observation_id": r.observation_id, "side": int(r.side), "decision_ts": int(r.decision_ts),
                    "entry_ts": int(r.one_second_entry_ts), "net": float(r.one_second_net),
                    "feature_ts": t0, "btc_oi_change": rates.get("BTCUSDT"),
                    "eth_oi_change": rates.get("ETHUSDT"), "gate": allow, "feature_status": status})
            u = int(ref["paired_unknown"])
            base = metrics(results, u)
            assert base["verified_events"] == ref["one_second"]["trades"] and base["wins"] == ref["one_second"]["wins"]
            assert abs(base["mean_net_pct_notional"] - ref["one_second"]["mean_net_pct_notional"]) < 1e-10
            valid = [r for r in results if r["gate"] is True]
            removed = [r for r in results if r["gate"] is False]
            unknown = [r for r in results if r["gate"] is None]
            assert len(results) == len(valid) + len(removed) + len(unknown)
            rows.append({"year": year, "leverage": lev, "variant": "one_second",
                "baseline": base, "oi_gate": metrics(valid, u + len(unknown)),
                "known_filtered": metrics(removed, 0), "original_unknown": u,
                "additional_feature_unknown": len(unknown)})
            all_detail.extend(results)
    df = pd.DataFrame(all_detail)
    detail = H / "持仓量门逐笔机会.csv"
    df.to_csv(detail, index=False, encoding="utf-8-sig")
    output = {"rows": rows, "feature_tests": test_feature(), "plan_sha256": qa["plan_sha256"],
              "oi_input_sha256": digest(points), "data_quality_sha256": digest(src),
              "previous_trade_summary_sha256": five_hash, "detail_sha256": digest(detail),
              "code_sha256": digest(Path(__file__)),
              "note": "Exploratory historical unit opportunities; timestamp publication latency and account outcomes unverified."}
    (H / "持仓量门跨期对照.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
