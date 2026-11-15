"""Re-download official risk sources and independently recompute each settled path."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import pandas as pd
import requests

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(bulk.R90))
import settle_risk_2022 as risk
sys.path.insert(0, str(R100))
spec = importlib.util.spec_from_file_location("ext100_risk_audit_109", R100 / "audit_exit.py")
prior_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior_audit)
BASE = "https://data.binance.vision/data/futures/um/monthly/"


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-12)


def main():
    bulk.runner.guard(start=True)
    ledger_path = H / "三日单位风险账本.json"
    doc = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert doc["paths_sha256"] == bulk.sha(H / "三日逐笔路径.json")
    assert doc["sources_sha256"] == bulk.sha(H / "三日风险来源.json")
    assert doc["risk_code_sha256"] == bulk.sha(H / "settle_pilot.py")
    sources = json.loads((H / "三日风险来源.json").read_text(encoding="utf-8"))
    marks, funds, statuses, unresolved = {}, {}, {}, []
    checked_sources = 0
    for item in sources["sources"]:
        bulk.runner.guard()
        kind, sym, month = item["kind"], item["contract"], item["month"]
        statuses[(kind, sym, month)] = item["status"]
        if item["status"] != "verified":
            unresolved.append({"kind": kind, "contract": sym, "month": month, "status": item["status"]})
            continue
        assert item["cache_path"] and bulk.sha(item["cache_path"]) == item["cache_sha256"]
        name = f"{sym}-1m-{month}.zip" if kind == "markPriceKlines" else f"{sym}-fundingRate-{month}.zip"
        sub = f"markPriceKlines/{sym}/1m/" if kind == "markPriceKlines" else f"fundingRate/{sym}/"
        url = BASE + sub + name
        ck = requests.get(url + ".CHECKSUM", timeout=(15, 50))
        ck.raise_for_status()
        fields = ck.text.strip().split()
        assert len(fields) >= 2 and fields[0].lower() == item["sha256"] and Path(fields[1]).name == name
        response = requests.get(url, timeout=(15, 100))
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
        raw = risk.read_risk_csv(response.content, kind)
        if kind == "markPriceKlines":
            cols = ["open_time", "open", "high", "low", "close"]
            raw = raw[cols].apply(pd.to_numeric, errors="raise").rename(columns={"open_time": "ts"})
            wanted = set(item["requested_minutes"])
            fresh = {int(r["ts"]): r for r in raw[raw.ts.isin(wanted)].to_dict("records")}
            cached = {int(r["ts"]): r for r in item["rows"]}
            assert set(fresh) == set(cached)
            for ts, row in fresh.items():
                assert all(close(row[k], cached[ts][k]) for k in ("open", "high", "low", "close"))
                marks[(sym, ts)] = row
        else:
            cols = ["calc_time", "funding_interval_hours", "last_funding_rate"]
            raw = raw[cols].apply(pd.to_numeric, errors="raise").rename(columns={"calc_time": "ts"})
            fresh = {int(r["ts"]): r for r in raw.to_dict("records")}
            cached = {int(r["ts"]): r for r in item["rows"]}
            assert set(fresh) == set(cached)
            for ts, row in fresh.items():
                assert close(row["funding_interval_hours"], cached[ts]["funding_interval_hours"])
                assert close(row["last_funding_rate"], cached[ts]["last_funding_rate"])
            funds[(sym, month)] = list(fresh.values())
        checked_sources += 1
        print("EXT109_RISK_AUDIT_SOURCE", checked_sources, "/", len(sources["sources"]), kind, sym, month, flush=True)
    raw_paths = json.loads((H / "三日逐笔路径.json").read_text(encoding="utf-8"))["paths"]
    assert len(raw_paths) == len(doc["ledger"])
    settlements = 0
    for p, row in zip(raw_paths, doc["ledger"]):
        assert (p["observation_id"], p["contract"], p["leverage"], p["target_r"], p["status"]) == (
            row["observation_id"], row["contract"], row["leverage"], row["target_r"], row["status"])
        if p["status"] != "verified":
            assert row["category"] == ("no_order" if p["status"] in ("no_order_time", "known_risk_rejected") else "unknown_path")
            continue
        if row["risk_status"] == "verified":
            prior_audit.audit_risk(row, marks, funds, statuses)
            assert row["category"] == ("unknown_risk" if bool(row["liq_proxy"]) else "trade")
            settlements += 1
        else:
            assert row["category"] == "unknown_risk"
    out = {"all_checks_pass": True, "sources_checked": checked_sources, "unresolved_source_groups": unresolved,
           "path_classifications_checked": len(doc["ledger"]), "risk_settlements_checked": settlements,
           "ledger_sha256": bulk.sha(ledger_path), "source_sha256": bulk.sha(H / "三日风险来源.json"),
           "audit_code_sha256": bulk.sha(Path(__file__)),
           "note": "Official archives re-downloaded; unknown groups remain unknown; mark prices are minute-level proxies."}
    (H / "三日风险独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT109_RISK_AUDIT", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
