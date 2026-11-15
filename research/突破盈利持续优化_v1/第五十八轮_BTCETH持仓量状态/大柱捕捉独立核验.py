"""Independent set-join verification of post-close capture counts."""
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


def barset(df):
    return set(zip(df.contract, df.quarter_start.astype("int64"), df.allowed_side.astype("int64")))


def main():
    labels = pd.read_parquet(CAP / "跨期事后大柱标签.parquet")
    trades = pd.read_csv(H / "持仓量门逐笔机会.csv", dtype={"year": str})
    output_file = H / "大柱捕捉事后诊断.json"
    out = json.loads(output_file.read_text(encoding="utf-8"))
    regular = json.loads((R47 / "单次重试跨期单位对照.json").read_text(encoding="utf-8"))["rows"]
    for row in out["rows"]:
        year, lev, variant = row["year"], row["leverage"], row["variant"]
        label = labels[(labels.source_year == year) & (labels.status == "verified") & (labels.large == True)]
        trade = trades[(trades.year == year) & (trades.leverage == lev) & (trades.variant == variant)]
        match = label.merge(trade, on="observation_id", how="inner", validate="one_to_one")
        match = match[(match.side == match.allowed_side) & (match.entry_ts < match.quarter_start + 900_000)]
        baseline, gated, new_unknown = barset(match), barset(match[match.gate == True]), barset(match[match.gate.isna()])
        if variant == "five_second":
            ref = next(r for r in regular if r["year"] == year and r["leverage"] == lev and r["strategy"] == "single_retest")
            unknown_ids = set(ref["unknown_observation_ids"])
        else:
            comparison = json.loads((R51 / f"{year}一秒五秒配对对照.json").read_text(encoding="utf-8"))["rows"]
            unknown_ids = set(next(r for r in comparison if r["leverage"] == lev)["unknown_ids"])
        old_unknown = barset(label[label.observation_id.isin(unknown_ids)])
        assert row["known_large_bars"] == len(barset(label))
        assert row["baseline_captured"] == len(baseline) and row["oi_gate_captured"] == len(gated)
        assert row["baseline_unknown"] == len(old_unknown - baseline)
        assert row["oi_gate_unknown"] == len((old_unknown | new_unknown) - gated)
    proof = {"all_checks_pass": True, "groups_checked": len(out["rows"]),
             "result_sha256": sha(output_file), "detail_sha256": sha(H / "大柱捕捉事后明细.csv"),
             "audit_sha256": sha(Path(__file__))}
    (H / "大柱捕捉独立核验.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
