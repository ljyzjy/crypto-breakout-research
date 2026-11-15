"""Isolated date extension of the already audited fixed-11 minute-candidate engine."""
from collections import Counter
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import types

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
REF = H.parent / "第四十六轮_固定十一加密币跨时段"
P = H.parent
sys.path.insert(0, str(REF))
sys.path.insert(0, str(P / "第四十轮_BTC_ETH事前活跃度"))
import prepare_fixed11_chunked as prep
import minute_features_chunked as original_features
import chunk_exact
from market_decisions import classify

M, Q, DAY = 60_000, 900_000, 86_400_000
START, BEGIN, END = "2026-04-01", "2026-08-01", "2026-11-01"
SYMBOLS = prep.SYMBOLS


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ms(value):
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def patched_features():
    source = (REF / "minute_features_chunked.py").read_text(encoding="utf-8")
    old = "elif year==2026:lo=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2026-08-01',tz='UTC').timestamp()*1000)"
    new = "elif year==2026:lo=int(EXT_BEGIN_MS);hi=int(EXT_END_MS)"
    assert source.count(old) == 1
    code = source.replace(old, new)
    module = types.ModuleType("ext63_features")
    module.__file__ = str(REF / "minute_features_chunked.py")
    module.EXT_BEGIN_MS, module.EXT_END_MS = ms("2026-05-01"), ms("2026-08-01")
    sys.modules[module.__name__] = module
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    return module, hashlib.sha256(code.encode()).hexdigest()


def parity_and_causality(module, input_path):
    frame = pd.read_parquet(input_path)
    lo, hi = ms("2026-06-01"), ms("2026-06-08")
    frame = frame[frame.ts.between(lo, hi - 1)].sort_values("ts")
    grid = np.arange(lo, hi, M, dtype=np.int64)
    assert len(frame) == len(grid) and np.array_equal(frame.ts.to_numpy(np.int64), grid)
    a = frame[["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]].to_numpy(float)
    days = set(pd.to_datetime(grid[::1440], unit="ms", utc=True).strftime("%Y-%m-%d"))
    hour1, rows1, count1 = original_features.derive(a, grid, "BTCUSDT", 2026, days)
    hour2, rows2, count2 = module.derive(a, grid, "BTCUSDT", 2026, days)
    pd.testing.assert_frame_equal(hour1, hour2, check_exact=True)
    assert rows1 == rows2 and count1 == count2
    modified = a.copy()
    cutoff = len(grid) - 1440
    modified[cutoff:, :4] *= 1.01
    modified[cutoff:, 4:] *= 1.05
    _, changed, _ = module.derive(modified, grid, "BTCUSDT", 2026, days)
    cut_ts = int(grid[cutoff])
    assert [x for x in rows2 if x["trigger_minute"] < cut_ts] == [x for x in changed if x["trigger_minute"] < cut_ts]
    return {"all_checks_pass": True, "real_minute_rows": len(grid), "original_period_candidate_count": len(rows1),
            "checks": ["original period exact hourly and candidate parity", "future-minute perturbation"]}


def main():
    frozen_path = H / "行情代码冻结哈希.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    assert frozen["plan_sha256"] == sha(H / "冻结研究方案.md")
    for sym, item in frozen["source"].items():
        assert sha(Path(item["path"])) == item["sha256"], sym
    for key, item in frozen["dependencies"].items():
        assert sha(Path(item["path"])) == item["sha256"], key
    module, patch_hash = patched_features()
    parity = parity_and_causality(module, Path(frozen["source"]["BTCUSDT"]["path"]))
    module.EXT_BEGIN_MS, module.EXT_END_MS = ms(BEGIN), ms(END)
    chunk_exact.m = module
    prep.derive = chunk_exact.derive_chunked
    prep.WINDOWS = {2026: (START, BEGIN, END)}
    prep.WORK = H / "小块缓存"
    prep.WORK.mkdir(exist_ok=True)
    fingerprint = hashlib.sha256((sha(frozen_path) + sha(Path(__file__)) + patch_hash).encode()).hexdigest()
    records = []
    for sym in SYMBOLS:
        src = Path(frozen["source"][sym]["path"])
        records.append(prep.process(2026, sym, src, fingerprint))
        print("EXT63_SYMBOL", len(records), "/", len(SYMBOLS), sym, flush=True)
    out = H / "候选数据"
    out.mkdir(exist_ok=True)
    days = pd.concat([pd.read_parquet(r["days_path"]) for r in records], ignore_index=True)
    days = days[days.day.ge(BEGIN) & days.day.lt(END) & np.isfinite(days.past_30d_quote)].copy()
    days["eligible_count"] = days.groupby("day").symbol.transform("size")
    days = days[days.eligible_count.eq(11)]
    days = days.sort_values(["day", "past_30d_quote", "symbol"], ascending=[True, False, True])
    days["liquidity_rank"] = days.groupby("day").cumcount() + 1
    days.to_parquet(out / "固定十一币历史日排名.parquet", index=False)
    indicator = prep.hourly_indicator()
    hourly = []
    for r in records:
        f = indicator(pd.read_parquet(r["hours_path"]), START, END)
        f["symbol"] = r["symbol"]
        hourly.append(f)
    f = pd.concat(hourly, ignore_index=True)
    f["day"] = pd.to_datetime(f.decision_hour, unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    merged = days[["day", "symbol", "liquidity_rank"]].merge(f, on=["day", "symbol"], how="left", validate="one_to_many")
    assert len(merged) == 24 * len(days)
    merged["valid_feature"] = np.isfinite(merged.score) & np.isfinite(merged.rvol)
    merged["valid_count"] = merged.groupby("decision_hour").valid_feature.transform("sum")
    complete = merged[merged.valid_count.eq(11)]
    eligible = complete[complete.valid_feature & complete.rvol.ge(1.5) & complete.score.ne(0)].copy()
    eligible["side"] = np.where(eligible.score > 0, 1, -1)
    eligible["strength"] = eligible.score.abs()
    eligible = eligible.sort_values(["decision_hour", "side", "strength", "liquidity_rank", "symbol"], ascending=[True, True, False, True, True])
    eligible["hourly_rank"] = eligible.groupby(["decision_hour", "side"]).cumcount() + 1
    top = eligible[eligible.hourly_rank <= 3]
    top.to_parquet(out / "固定十一币已知小时排名.parquet", index=False)
    events = [pd.read_parquet(r["events_path"]) for r in records]
    events = [x for x in events if len(x)]
    assert events
    raw = pd.concat(events, ignore_index=True)
    assert raw.observation_id.is_unique
    raw = raw[raw.quarter_end + M <= ms(END)].copy()
    raw.to_parquet(out / "固定十一币潜在分钟候选.parquet", index=False)
    bars = pd.concat([pd.read_parquet(r["market_path"]) for r in records if r["market_path"]], ignore_index=True)
    assert not bars.duplicated(["symbol", "open_time"]).any()
    bars.to_parquet(out / "BTC_ETH一分钟合成十五分钟.parquet", index=False)
    lookup = {(x["symbol"], int(x["open_time"])): x for x in bars.to_dict("records")}
    ranks = {(int(r.decision_hour), r.symbol, int(r.side)): {"score": float(r.score), "rvol": float(r.rvol),
              "rank": int(r.hourly_rank), "liquidity_rank": int(r.liquidity_rank)} for r in top.itertuples(index=False)}
    quarters = sorted(set(map(int, raw.quarter_start)))
    markets = {q: classify(q, lookup, set()) for q in quarters}
    events, counts = [], Counter()
    for e in raw.to_dict("records"):
        hour = int(e["trigger_minute"]) // 3_600_000 * 3_600_000
        both = markets[int(e["quarter_start"])]
        for side, name in ((1, "long"), (-1, "short")):
            detail = ranks.get((hour, e["symbol"], side))
            is_eligible = bool(e[name + "_pre_rank"] and detail is not None)
            if is_eligible:
                e[name + "_spec"] = json.dumps({**json.loads(e[name + "_spec"]), **detail}, ensure_ascii=False)
            allowed = both["market_status"] == "market_unknown" or (both["market_status"] == "allowed" and both["allowed_side"] == side)
            e[name + "_known_eligible"] = bool(is_eligible and allowed)
            if not e[name + "_known_eligible"]:
                e[name + "_spec"] = "null"
        if e["long_known_eligible"] or e["short_known_eligible"]:
            e["market_prior_status"], e["market_allowed_side"] = both["market_status"], both["allowed_side"]
            e["needs_next"] = bool((int(e["quarter_end"]) + M - 1) // DAY > int(e["trigger_minute"]) // DAY)
            events.append(e)
            counts[both["market_status"]] += 1
        else:
            counts["filtered_before_tick"] += 1
    candidates = pd.DataFrame(events).sort_values(["trigger_minute", "symbol"]).reset_index(drop=True)
    assert candidates.observation_id.is_unique and not candidates.duplicated(["symbol", "quarter_start"]).any()
    candidates.to_parquet(out / "固定十一币双币过滤潜在触价.parquet", index=False)
    output_files = sorted(out.glob("*.parquet"))
    data = {"period_utc": [BEGIN, END], "warm_start_utc": START, "symbols": SYMBOLS,
            "calendar_days": (pd.Timestamp(END) - pd.Timestamp(BEGIN)).days,
            "complete_liquidity_days": int(days.day.nunique()), "rankable_hours": int(complete.decision_hour.nunique()),
            "raw_potential_events": len(raw), "post_hour_and_market_candidates": len(candidates),
            "candidate_market_statuses": candidates.market_prior_status.value_counts().to_dict(),
            "market_quarter_statuses": dict(Counter(v["market_status"] for v in markets.values())),
            "parity_and_causality": parity, "patched_feature_sha256": patch_hash,
            "sources_sha256": sha(frozen_path), "code_sha256": sha(Path(__file__)),
            "outputs_sha256": {p.name: sha(p) for p in output_files},
            "note": "Minute candidates only: no tick confirmation, order, risk or profitability."}
    (H / "延伸候选准备质量.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXT63_CANDIDATES", json.dumps(data, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
