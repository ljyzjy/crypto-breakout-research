"""Post-close descriptive capture diagnostic, never an entry condition."""
from pathlib import Path
import hashlib
import json

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
CAP = P / "第五十三轮_跨期大柱捕捉诊断"
PREV = P / "第四十七轮_一次重新突破确认"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    files = [H / "资金费门对大柱捕捉的事后诊断方案.md", H / "已核验机会及资金费门.csv",
             H / "资金费门独立核验.json", CAP / "跨期事后大柱标签.parquet",
             CAP / "跨期大柱捕捉对照.json", PREV / "单次重试跨期单位对照.json", Path(__file__)]
    audit = json.loads(files[2].read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["detail_sha256"] == sha(files[1])
    gates = pd.read_csv(files[1], dtype={"year": str})
    labels = pd.read_parquet(files[3])
    old_capture = json.loads(files[4].read_text(encoding="utf-8"))["rows"]
    old_results = json.loads(files[5].read_text(encoding="utf-8"))["rows"]
    summaries, details = [], []
    for year in ("2024", "2026"):
        lb = labels[labels.source_year.eq(year)]
        for lev in (10, 20):
            gate = gates[(gates.year == year) & (gates.leverage == lev)].set_index("observation_id")
            old = next(r for r in old_results if r["year"] == year and r["leverage"] == lev
                       and r["strategy"] == "single_retest")
            old_cap = next(r for r in old_capture if r["year"] == year and r["leverage"] == lev
                           and r["strategy"] == "single_retest")
            unknown = set(old["unknown_observation_ids"])
            assert set(gate.index) == set(old["verified_observation_ids"])
            row = {"year": year, "leverage": lev, "known_large_bars": 0,
                   "baseline_captured": 0, "baseline_unknown": 0,
                   "gate_captured": 0, "gate_unknown": 0}
            for (contract, start, side), group in lb.groupby(["contract", "quarter_start", "allowed_side"]):
                if not group.status.eq("verified").all() or not bool(group.large.iloc[0]):
                    continue
                assert group.large.nunique() == 1
                ids = set(group.observation_id)
                known = []
                for obs in ids.intersection(gate.index):
                    r = gate.loc[obs]
                    if int(r.side) == int(side) and int(r.entry_ts) < int(start) + 900_000:
                        known.append((obs, bool(r.allowed)))
                before = bool(known)
                after = any(allow for _, allow in known)
                uncertain = bool(ids.intersection(unknown))
                row["known_large_bars"] += 1
                row["baseline_captured"] += int(before)
                row["baseline_unknown"] += int(not before and uncertain)
                row["gate_captured"] += int(after)
                row["gate_unknown"] += int(not after and uncertain)
                details.append({"year": year, "leverage": lev, "contract": contract,
                    "quarter_start": int(start), "side": int(side), "baseline_captured": before,
                    "gate_captured": after, "possible_unknown_after_gate": bool(not after and uncertain)})
            assert row["known_large_bars"] == old_cap["verified_large_bars"]
            assert row["baseline_captured"] == old_cap["verified_captured_bars"]
            assert row["baseline_unknown"] == old_cap["unknown_capture_bars"]
            summaries.append(row)
    out = {"rows": summaries, "provenance_sha256": {str(p): sha(p) for p in files},
           "note": "Post-close diagnostic on existing candidates only; no future label used for entry."}
    (H / "资金费门大柱捕捉诊断.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(details).to_csv(H / "资金费门大柱捕捉事后明细.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == "__main__":
    main()
