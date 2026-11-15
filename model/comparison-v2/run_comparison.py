"""Staged, auditable Freqtrade comparisons; no optimization, no live operations."""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
MAIN = ["SpotTrendV1", "DailyDonchian", "DailyMA", "DailyMomentum", "DailyBollinger"]
NEIGHBORS = ["DonchianLow", "DonchianHigh", "MALow", "MAHigh", "MomentumLow", "MomentumHigh", "BollingerLow", "BollingerHigh"]
WINDOWS = {"2023": ("20230101", "20240101"), "2024": ("20240101", "20250101"),
           "2025": ("20250101", "20260101"), "2026": ("20260101", "20261101"),
           "evaluation": ("20250101", "20261101"), "full": ("20230101", "20261101")}


def timerange(window):
    start, end = WINDOWS[window]
    to_ts = lambda x: int(datetime.strptime(x, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
    return f"{to_ts(start)}-{to_ts(end)-1}"


def fingerprint():
    files = [OUT / "PROTOCOL.md", ROOT / "user_data/strategies/DailyCandidates.py",
             ROOT / "user_data/strategies/SpotTrendV1.py", ROOT / "config.paper.json",
             ROOT / "config.public-data.json"]
    files += sorted((ROOT / "user_data/data/binance").glob("*.feather"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def extract(folder, label, fee):
    archives = sorted(folder.glob("*.zip"))
    if not archives:
        raise RuntimeError(f"No result artifact: {folder}")
    path = archives[-1]
    rows = []
    with zipfile.ZipFile(path) as archive:
        payload = json.loads(archive.read(path.stem + ".json"))
        for name, s in payload["strategy"].items():
            wallet_file = next(n for n in archive.namelist() if n.endswith(f"_{name}_wallet.feather"))
            wallet = pd.read_feather(io.BytesIO(archive.read(wallet_file)))
            equity = wallet.groupby("date")["total_quote"].sum().sort_index()
            equity.loc[pd.Timestamp(s["backtest_start"], tz="UTC")] = 1000
            equity = equity.sort_index()
            dd = float((1-equity/equity.cummax()).max())
            positive = sorted([t["profit_abs"] for t in s["trades"] if t["profit_abs"] > 0], reverse=True)
            months = s.get("periodic_breakdown", {}).get("month", [])
            row = {"scenario": label, "strategy": name, "fee": fee,
                   "start": s["backtest_start"], "end": s["backtest_end"],
                   "profit": s["profit_total_abs"], "return_pct": s["profit_total"]*100,
                   "dd_pct": dd*100, "trades": s["total_trades"],
                   "winrate": s["winrate"], "profit_factor": s["profit_factor"],
                   "top3_gross_profit_share": sum(positive[:3])/sum(positive) if positive else None,
                   "pair_profit": {p["key"]:p["profit_total_abs"] for p in s["results_per_pair"] if p["key"] != "TOTAL"},
                   "worst_month_profit": min([m["profit_abs"] for m in months], default=0),
                   "best_month_profit": max([m["profit_abs"] for m in months], default=0),
                   "source_zip": str(path.relative_to(OUT))}
            rows.append(row)
            eq_dir = OUT / "equity"
            eq_dir.mkdir(exist_ok=True)
            equity.rename("equity_usdt").to_csv(eq_dir / f"{label}-{name}.csv")
    return rows


def run_one(window, fee, names, detail=False, diagnostic=False):
    label = f"{window}-fee{fee:.3f}" + ("-5m" if detail else "") + ("-neighbors" if diagnostic else "")
    folder = OUT / "results" / label
    folder.mkdir(parents=True, exist_ok=True)
    saved = folder / "metrics.json"
    if saved.exists():
        return json.loads(saved.read_text())
    args = [sys.executable, "-m", "freqtrade", "backtesting", "--config", "config.paper.json",
            "--config", "config.public-data.json", "--userdir", "user_data",
            "--strategy-list", *names, "--timerange", timerange(window), "--fee", str(fee),
            "--enable-protections", "--cache", "none", "--export", "trades",
            "--breakdown", "month", "year", "--backtest-directory", str(folder)]
    if detail:
        args += ["--timeframe-detail", "5m"]
    (folder / "command.json").write_text(json.dumps(args, indent=2), encoding="utf-8")
    env = dict(os.environ, FREQTRADE__DRY_RUN="true")
    with (folder / "run.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    if result.returncode:
        raise RuntimeError(f"Failed {label}; see {folder / 'run.log'}")
    rows = extract(folder, label, fee)
    if {r['strategy'] for r in rows} != set(names):
        raise RuntimeError(f"Incomplete strategy set: {label}")
    saved.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"DONE {label}: " + ", ".join(f"{r['strategy']}={r['return_pct']:.2f}%" for r in rows), flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["selection", "evaluation"])
    args = parser.parse_args()
    fp = OUT / "fingerprint.json"
    current = fingerprint()
    if fp.exists():
        if json.loads(fp.read_text()) != current:
            raise RuntimeError("Protocol/code/data fingerprint changed. Create a new experiment version.")
    else:
        fp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    if args.stage == "selection":
        rows = []
        for window in ["2023", "2024"]:
            for fee in [.001, .002]:
                rows += run_one(window, fee, MAIN)
        ranking = []
        for name in MAIN[1:]:
            own = [r for r in rows if r["strategy"] == name]
            stress = [r for r in own if r["fee"] == .002]
            count = sum(r['trades'] for r in own if r['fee'] == .001)
            ranking.append({"strategy": name, "eligible_early": all(r['profit'] > 0 and r['dd_pct'] <= 10 for r in own) and count >= 30,
                            "worst_year_stress_return": min(r['return_pct'] for r in stress),
                            "mean_stress_return": sum(r['return_pct'] for r in stress)/2,
                            "early_base_trades": count})
        ranking.sort(key=lambda r: (not r['eligible_early'], -r['worst_year_stress_return'], -r['mean_stress_return'], r['early_base_trades']))
        frozen = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(), "ranking": ranking,
                  "method": "2023/2024 only; do not reorder using evaluation results"}
        rank_file = OUT / "frozen_selection.json"
        if not rank_file.exists():
            rank_file.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
        pd.DataFrame(rows).to_csv(OUT / "selection.csv", index=False)
        print(json.dumps(frozen, indent=2), flush=True)
    else:
        if not (OUT / "frozen_selection.json").exists():
            raise RuntimeError("Run and freeze selection first")
        for window in ["2025", "2026", "evaluation"]:
            for fee in [.001, .002, .003]:
                run_one(window, fee, MAIN)
        run_one("full", .001, MAIN)
        run_one("evaluation", .001, MAIN, detail=True)
        run_one("evaluation", .002, NEIGHBORS, diagnostic=True)
    all_rows = []
    for saved in sorted((OUT / "results").glob("*/metrics.json")):
        all_rows += json.loads(saved.read_text())
    (OUT / "all_metrics.json").write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
    pd.DataFrame(all_rows).to_csv(OUT / "all_metrics.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
