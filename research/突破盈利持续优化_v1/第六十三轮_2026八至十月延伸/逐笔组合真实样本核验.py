"""Replay two previously audited original/retest events against the composition."""
from pathlib import Path
import hashlib
import json
import math
import shutil
import sys
import time

import pandas as pd
import psutil

H = Path(__file__).resolve().parent
P = H.parent
for folder in ("第三十三轮_动态池逐笔执行", "第四十八轮_固定一倍风险止盈"):
    sys.path.insert(0, str(P / folder))
import extract_dynamic_tapes as engine
import public_range
import 逐笔组合决策 as composed

SAMPLES = (("opening|NEARUSDT|1785193200000", "original"),
           ("touch|DOGEUSDT|1783290000000", "retest"))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def guard():
    if shutil.disk_usage(H).free < 2_200_000_000:
        raise RuntimeError("disk_headroom")
    if psutil.virtual_memory().available < 250 * 1024**2:
        raise RuntimeError("memory_headroom")


def equal(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def main():
    while psutil.virtual_memory().available < 500 * 1024**2:
        guard(); time.sleep(3)
    guard()
    test = json.loads((H / "逐笔组合合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["composition_sha256"] == sha(H / "逐笔组合决策.py")
    prior = P / "第四十七轮_一次重新突破确认"
    one = P / "第五十一轮_缩短市价入场延迟"
    source = pd.read_parquet(prior / "跨期冻结输入" / "2026_signal.parquet").set_index("observation_id")
    retry = pd.read_parquet(prior / "2026重试分批" / "动态池逐笔信号筛查.parquet").set_index("observation_id")
    paths = pd.read_parquet(one / "2026一秒入场分批" / "动态池延迟市价路径.parquet")
    previous = json.loads((one / "2026一秒入场逐笔独立抽查.json").read_text(encoding="utf-8"))
    assert previous["all_checks_pass"]
    out = []
    for obs, origin in SAMPLES:
        original = source.loc[obs].to_dict(); original["observation_id"] = obs
        day, symbol = str(original["day"]), original["contract"]
        body, bar_meta = engine.archive("klines", symbol, day)
        bars = engine.minute_bars(body, day)
        windows = {obs: (int(original["trigger_minute"]), int(original["quarter_end"]) + 60_000)}
        blocks, meta = public_range.fetch(symbol, day, windows, guard)
        expected = next(s for s in previous["samples"] if s["observation_id"] == obs)
        assert meta["sha256"] == expected["archives"][0]["sha256"]
        tape = blocks[obs].sort_values(["transact_time", "agg_trade_id"], kind="mergesort")
        result = composed.decide(original, tape, bars)
        assert result["origin"] == origin and result["chosen"]["status"] == "qualified"
        expected_signal = original if origin == "original" else retry.loc[obs].to_dict()
        for field in ("side", "decision_ts", "entry_exec_ts", "raw_entry_5s", "stop_price", "level"):
            assert equal(result["chosen"][field], expected_signal[field]), (obs, field)
        for lev in (10, 20):
            item = paths[(paths.observation_id == obs) & (paths.variant == f"one_second_2r_{lev}x")]
            assert len(item) == 1
            expected_path = item.iloc[0]
            got = result["paths_1s"][f"one_second_2r_{lev}x"]
            for field in ("status", "entry_ts", "entry_raw", "entry_fill", "exit_signal_ts", "exit_ts", "exit_raw", "exit_fill", "reason", "initial_stop"):
                assert equal(got[field], expected_path[field]), (obs, lev, field)
        out.append({"observation_id": obs, "origin": origin, "ohlc_sha256": bar_meta["sha256"],
                    "agg_trade_sha256": meta["sha256"], "paths_checked": 2})
        print("EXT63_REAL_SAMPLE", len(out), "/", len(SAMPLES), flush=True)
    proof = {"all_checks_pass": True, "samples": out, "composition_sha256": sha(H / "逐笔组合决策.py"),
             "test_sha256": sha(Path(__file__)), "note": "Previously audited same-exchange samples; not new-period trades."}
    (H / "逐笔组合真实样本核验.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXT63_REAL_SAMPLES_PASS", flush=True)


if __name__ == "__main__":
    main()
