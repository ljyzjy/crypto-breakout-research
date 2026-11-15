"""Resettle verified cross-period trailing paths against original risk sources."""
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import replay_cross as replay

H, P = replay.H, replay.P
sys.path.insert(0, str(replay.R70))
import settle_1r_local as prior
M = 60000


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def main(year):
    replay.bulk.runner.guard(start=True)
    tasks, ref = replay.frozen(year)
    fp = replay.identity(year)
    progress = json.loads((H / f"{year}跟踪逐笔回放进度.json").read_text(encoding="utf-8"))
    assert progress["fingerprint"] == fp and progress["code_sha256"] == replay.bulk.sha(H / "replay_cross.py")
    snapshot = P / f"第六十二轮_一秒观察更早突破/{year}完整批次_冻结"
    manifest = json.loads((snapshot / "完整快照哈希.json").read_text(encoding="utf-8"))
    risk_name = "batch/动态池风险档案核验清单.json"
    assert replay.bulk.sha(snapshot / risk_name) == manifest["files"][risk_name]
    expected_list = json.loads((snapshot / risk_name).read_text(encoding="utf-8"))
    expected = {(x["kind"], x["contract"], x["month"]): x for x in expected_list}
    assert len(expected) == len(expected_list)
    ledger = pd.read_parquet(snapshot / "batch/动态池单位收益与风险.parquet")
    old_ledger = {(x["observation_id"], x["variant"]): x for x in ledger.to_dict("records")}
    needed, pairs, missing = {}, [], []
    for task in tasks:
        cp_path = replay.cp_path(year, fp, task)
        cp = json.loads(cp_path.read_text(encoding="utf-8")) if cp_path.exists() else None
        if cp:
            assert cp["fingerprint"] == fp and cp["source_checkpoint"] == task["checkpoint"] and cp["status"] == "verified"
        rows = {x["observation_id"]: x for x in cp["rows"]} if cp else {}
        for event in task["events"]:
            obs = event["observation_id"]
            for variant, old in event["old_paths"].items():
                alt = rows.get(obs, {}).get("paths", {}).get(variant)
                if not alt or alt.get("status") != "verified":
                    missing.append({"observation_id": obs, "variant": variant, "status": (alt or {}).get("status", "replay_unknown")})
                    continue
                assert int(alt["entry_ts"]) == int(old["entry_ts"]) and near(alt["entry_fill"], old["entry_fill"])
                assert int(alt["exit_ts"]) <= int(old["exit_ts"]) and int(alt["exit_signal_ts"]) <= int(old["exit_signal_ts"])
                for ts in range(int(old["entry_ts"]) // M * M, int(old["exit_ts"]) // M * M + M, M):
                    needed.setdefault((task["contract"], prior.month(ts)), set()).add(ts)
                pairs.append((task["contract"], event, variant, old, alt))
    assert len(pairs) + len(missing) == ref["paths"]
    # Reused risk reader also checks the same C/D and memory reserves on every source.
    prior.replay.guard = replay.bulk.runner.guard
    marks, funds, statuses, archives = prior.load_risk(year, needed, expected)
    engine_path = P / "第四十四轮_双币过滤跨时段复核/settle_cross_engine.py"
    spec = importlib.util.spec_from_file_location("ext113_crossrisk", engine_path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    records = []
    for contract, event, variant, old, alt in pairs:
        common = {"contract": contract, "side": event["side"]}
        before = engine.settle(SimpleNamespace(**{**old, **common, "variant": variant}), marks, funds, statuses)
        base = old_ledger[(event["observation_id"], variant)]
        if before["risk_status"] != "verified":
            records.append({"observation_id": event["observation_id"], "variant": variant, "status": "risk_source_unknown"})
            continue
        for field in ("funding", "entry_fee", "exit_fee", "net_per_unit_notional"):
            assert near(before[field], base[field]), (event["observation_id"], variant, field)
        assert bool(before["liq_proxy"]) == bool(base["liq_proxy"])
        after = engine.settle(SimpleNamespace(**{**alt, **common, "variant": variant}), marks, funds, statuses)
        records.append({"observation_id": event["observation_id"], "variant": variant, "contract": contract,
                        "side": event["side"], "decision_ts": event["decision_ts"], "quarter_end": event["quarter_end"],
                        **alt, **after, "baseline_2r_net": float(base["net_per_unit_notional"])})
    result = {"year": year, "source_snapshot_sha256": ref["source_snapshot_sha256"], "replay_fingerprint": fp,
              "eligible_2r_paths": ref["paths"], "replayed_pairs": len(pairs), "replay_unknown": missing,
              "risk_archives": archives, "records": records, "source_engine_sha256": replay.bulk.sha(engine_path),
              "settlement_code_sha256": replay.bulk.sha(Path(__file__)), "frozen_sha256": replay.bulk.sha(H / "输入冻结.json"),
              "note": "Risk proxy and public aggregate prints; missing source remains unknown."}
    (H / f"{year}跟踪退出风险账本.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT113_RISK", year, "paths", len(records), "unknown", len(missing),
          "source_unknown", sum(x["status"] != "verified" for x in archives), flush=True)


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in ("2024", "2026")
    main(sys.argv[1])
