"""Independent parser, stop/exit replay and funding checks for fixed samples."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
R104 = P / "第一百零四轮_同秒成交加速门"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(bulk.R93))
import audit_raw_samples
sys.path.insert(0, str(R100))
import run_exit as previous


def funding_class(symbol, start, end, funds, statuses):
    months = set()
    for t in range((start // 60000) * 60000, (end // 60000) * 60000 + 1, 60000):
        month = pd.Timestamp(t, unit="ms", tz="UTC").strftime("%Y-%m")
        months.add(month)
        if statuses.get(("fundingRate", symbol, month)) != "verified":
            return "unknown_funding_source"
        times = sorted((int(x["ts"]), D(str(x["funding_interval_hours"]))) for x in funds.get((symbol, month), []))
        if not times:
            return "unknown_funding_coverage"
        previous_rows = [x for x in times if x[0] <= t]
        later_rows = [x for x in times if x[0] > t]
        before = previous_rows[-1] if previous_rows else times[0]
        after = later_rows[0] if later_rows else times[-1]
        span = (after[0] - before[0]) if previous_rows and later_rows else (times[0][0] - t if not previous_rows else t - times[-1][0])
        if D(span) > max(before[1], after[1]) * D(3600000) * D("1.5"):
            return "unknown_funding_coverage"
    if any(start <= int(x["ts"]) <= end for month in months for x in funds[(symbol, month)]):
        return "unknown_funding_event"
    return "known"


def independently_evaluate(path, seq):
    side, start, end = int(path["side"]), int(path["entry_ts"]), int(path["quarter_end"])
    entry, stop = D(str(path["entry_fill"])), D(str(path["initial_stop"]))
    if side not in (-1, 1) or entry <= 0 or stop <= 0:
        return {"status": "unknown_invalid_entry"}
    first = next((x for x in seq if x[0] >= start), None)
    if first is None or first[0] != start:
        return {"status": "unknown_entry_tick"}
    if abs(first[2] - D(str(path["entry_raw"]))) > D("1e-9"):
        return {"status": "unknown_entry_mismatch"}
    breach = next((x[0] for x in seq if start <= x[0] < end and D(side) * (x[2] - stop) <= 0), end)
    deadline = start if path["reason"] == "filled_beyond_risk_budget" else breach
    forced = next((x for x in seq if x[0] >= deadline + 5000), None)
    if forced is None or forced[0] >= end + 60000:
        return {"status": "unknown_forced_exit", "deadline_ts": deadline}
    choices = [x for x in seq if start + 5000 <= x[0] <= deadline + 5000]
    if forced not in choices:
        choices.append(forced)
    if not choices:
        return {"status": "unknown_no_fill", "deadline_ts": deadline}
    best = max(choices, key=lambda x: D(side) * x[2])
    exit_fill = best[2] * (1 - D(side) * D("0.0005"))
    net = D(side) * (exit_fill - entry) / entry - D("0.0005") * (1 + exit_fill / entry)
    return {"status": "known", "deadline_ts": deadline, "forced_exit_ts": forced[0],
            "oracle_exit_ts": best[0], "oracle_exit_raw": str(best[2]), "oracle_net": str(net),
            "candidate_fill_count": len(choices)}


def near(a, b):
    return abs(D(str(a)) - D(str(b))) < D("1e-12")


def main():
    bulk.runner.guard(start=True)
    doc = json.loads((H / "退出上界逐笔.json").read_text(encoding="utf-8"))
    assert doc["code_sha256"] == bulk.sha(H / "run_oracle.py") and doc["frozen_sha256"] == bulk.sha(H / "输入冻结.json")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for path, digest in frozen["files"].items():
        assert bulk.sha(path) == digest
    wanted = set(json.loads((R104 / "研究冻结.json").read_text(encoding="utf-8"))["audit_sample_ids"])
    results = {(x["observation_id"], x["variant"]): x for x in doc["rows"]}
    original = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    assert len(results) == 261 and set(results) <= set(original)
    _, funds, statuses = previous.risk_inputs()
    classifications = 0
    for key, result in results.items():
        original_row = original[key]
        assert near(result["baseline_net"], original_row["net_per_unit_notional"])
        if "forced_exit_ts" in result:
            status = funding_class(result["contract"], result["entry_ts"], result["forced_exit_ts"], funds, statuses)
            assert status == result["status"]
            if status == "known":
                assert abs(D(str(original_row["funding"]))) < D("1e-12")
            classifications += 1
    candidates = pd.read_parquet(bulk.R90 / "候选数据/固定十一币双币过滤潜在触价.parquet")
    checked = 0
    obs_checked = set()
    for (sym, day), group in candidates.groupby(["contract", "day"], sort=True):
        events = group.to_dict("records")
        selected = [e for e in events if e["observation_id"] in wanted and any(k[0] == e["observation_id"] for k in results)]
        if not selected:
            continue
        bulk.runner.guard()
        cp_path = bulk.runner.ROOT / "raw_2022_full_checkpoints" / (bulk.runner.key(bulk.fingerprint(), sym, day, events) + ".json")
        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        assert cp["fingerprint"] == bulk.fingerprint() and cp["status"] == "verified"
        arcs = [x for x in cp["archives"] if x["kind"] == "trades"]
        for arc in arcs:
            assert bulk.sha(arc["path"]) == arc["sha256"]
        for event in selected:
            obs = event["observation_id"]
            keys = [k for k in results if k[0] == obs]
            paths = [{**original[k], "observation_id": k[0], "variant": k[1]} for k in keys]
            lo = min(int(x["entry_ts"]) for x in paths)
            hi = max(int(x["quarter_end"]) for x in paths) + 60000
            seq = []
            for arc in arcs:
                seq.extend(audit_raw_samples.independent_window(arc["path"], "trades", lo, hi))
            seq.sort(key=lambda x: (x[0], x[1]))
            for key, row in zip(keys, paths):
                actual = results[key]
                if actual["status"] == "unknown_raw_window":
                    continue
                calc = independently_evaluate(row, seq)
                if calc["status"] == "known":
                    funding = funding_class(sym, row["entry_ts"], calc["forced_exit_ts"], funds, statuses)
                    if funding != "known":
                        calc = {"status": funding, "deadline_ts": calc["deadline_ts"], "forced_exit_ts": calc["forced_exit_ts"]}
                for name, value in calc.items():
                    assert name in actual and (near(actual[name], value) if name in ("oracle_exit_raw", "oracle_net") else actual[name] == value), (key, name)
                checked += 1
            obs_checked.add(obs)
            print("EXT111_AUDIT", len(obs_checked), "/", len(wanted), checked, sym, day, flush=True)
    out = {"all_checks_pass": True, "funding_classifications_checked": classifications,
           "prespecified_sample_observations": len(wanted), "replayed_sample_observations": len(obs_checked),
           "replayed_sample_paths": checked, "source_sha256": bulk.sha(H / "退出上界逐笔.json"),
           "code_sha256": bulk.sha(Path(__file__)), "frozen_sample_sha256": bulk.sha(R104 / "研究冻结.json"),
           "note": "Independent pandas tick parser, scalar execution and funding classification; hindsight remains nontradable."}
    (H / "退出上界独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT111_AUDIT_COMPLETE", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
