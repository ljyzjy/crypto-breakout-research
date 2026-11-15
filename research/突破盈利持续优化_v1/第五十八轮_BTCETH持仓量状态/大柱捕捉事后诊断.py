"""Count captured future-defined bars; labels never enter the OI signal."""
from pathlib import Path
import hashlib
import json

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
CAP = P / "第五十三轮_跨期大柱捕捉诊断"
R47 = P / "第四十七轮_一次重新突破确认"
R51 = P / "第五十一轮_缩短市价入场延迟"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    trade = H / "持仓量门逐笔机会.csv"
    proof = json.loads((H / "持仓量门独立核验.json").read_text(encoding="utf-8"))
    assert proof["all_checks_pass"] and proof["detail_sha256"] == sha(trade)
    rows = pd.read_csv(trade, dtype={"year": str})
    labels = pd.read_parquet(CAP / "跨期事后大柱标签.parquet")
    previous = json.loads((CAP / "跨期大柱捕捉对照.json").read_text(encoding="utf-8"))["rows"]
    regular = json.loads((R47 / "单次重试跨期单位对照.json").read_text(encoding="utf-8"))["rows"]
    out, details = [], []
    for year in ("2024", "2026"):
        labels_year = labels[labels.source_year.eq(year)]
        one = json.loads((R51 / f"{year}一秒五秒配对对照.json").read_text(encoding="utf-8"))["rows"]
        for lev in (10, 20):
            baseline = next(x for x in regular if x["year"] == year and x["leverage"] == lev and x["strategy"] == "single_retest")
            fast = next(x for x in one if x["leverage"] == lev)
            old = next(x for x in previous if x["year"] == year and x["leverage"] == lev and x["strategy"] == "single_retest")
            for variant in ("five_second", "one_second"):
                frame = rows[rows.year.eq(year) & rows.leverage.eq(lev) & rows.variant.eq(variant)].set_index("observation_id")
                assert frame.index.is_unique
                unknown = set(baseline["unknown_observation_ids"] if variant == "five_second" else fast["unknown_ids"])
                result = {"year": year, "leverage": lev, "variant": variant, "known_large_bars": 0,
                    "baseline_captured": 0, "baseline_unknown": 0, "oi_gate_captured": 0, "oi_gate_unknown": 0}
                for (contract, start, side), group in labels_year.groupby(["contract", "quarter_start", "allowed_side"]):
                    if not group.status.eq("verified").all() or not bool(group.large.iloc[0]):
                        continue
                    assert group.large.nunique() == 1
                    ids = set(group.observation_id)
                    matches = []
                    for obs in ids.intersection(frame.index):
                        row = frame.loc[obs]
                        if int(row.side) == int(side) and int(row.entry_ts) < int(start) + 900_000:
                            matches.append(row.gate)
                    captured = bool(matches)
                    kept = any(v is True or v == True for v in matches if not pd.isna(v))
                    original_unknown = bool(ids.intersection(unknown))
                    new_unknown = original_unknown or any(pd.isna(v) for v in matches)
                    result["known_large_bars"] += 1
                    result["baseline_captured"] += int(captured)
                    result["baseline_unknown"] += int(not captured and original_unknown)
                    result["oi_gate_captured"] += int(kept)
                    result["oi_gate_unknown"] += int(not kept and new_unknown)
                    details.append({"year": year, "leverage": lev, "variant": variant, "contract": contract,
                        "quarter_start": int(start), "allowed_side": int(side), "baseline_captured": captured,
                        "oi_gate_captured": kept, "oi_gate_unknown": bool(not kept and new_unknown)})
                assert result["known_large_bars"] == old["verified_large_bars"]
                if variant == "five_second":
                    assert result["baseline_captured"] == old["verified_captured_bars"]
                    assert result["baseline_unknown"] == old["unknown_capture_bars"]
                out.append(result)
    detail_file = H / "大柱捕捉事后明细.csv"
    pd.DataFrame(details).to_csv(detail_file, index=False, encoding="utf-8-sig")
    output = {"rows": out, "detail_sha256": sha(detail_file), "gate_detail_sha256": sha(trade),
              "labels_sha256": sha(CAP / "跨期事后大柱标签.parquet"),
              "posthoc_one_second_plan_sha256": sha(H / "一秒大柱事后补充方案.md"),
              "code_sha256": sha(Path(__file__)),
              "note": "Post-close bar labels describe capture only and never determine entries."}
    (H / "大柱捕捉事后诊断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
