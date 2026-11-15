"""Independent set-join check of the post-close capture diagnostic."""
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
    labels = pd.read_parquet(CAP / "跨期事后大柱标签.parquet")
    gates = pd.read_csv(H / "已核验机会及资金费门.csv", dtype={"year": str})
    orig = json.loads((PREV / "单次重试跨期单位对照.json").read_text(encoding="utf-8"))["rows"]
    result = json.loads((H / "资金费门大柱捕捉诊断.json").read_text(encoding="utf-8"))
    checks = 0
    def barset(df):
        return set(zip(df.contract, df.quarter_start.astype("int64"), df.allowed_side.astype("int64")))
    for item in result["rows"]:
        year, lev = item["year"], item["leverage"]
        lb = labels[(labels.source_year == year) & (labels.status == "verified") & (labels.large == True)]
        gate = gates[(gates.year == year) & (gates.leverage == lev)]
        join = lb.merge(gate, on="observation_id", how="inner", validate="one_to_one")
        join = join[(join.side == join.allowed_side) & (join.entry_ts < join.quarter_start + 900_000)]
        before, after = barset(join), barset(join[join.allowed == True])
        ref = next(r for r in orig if r["year"] == year and r["leverage"] == lev and r["strategy"] == "single_retest")
        uncertain = barset(lb[lb.observation_id.isin(ref["unknown_observation_ids"])])
        assert item["known_large_bars"] == len(barset(lb))
        assert item["baseline_captured"] == len(before) and item["gate_captured"] == len(after)
        assert item["baseline_unknown"] == len(uncertain - before)
        assert item["gate_unknown"] == len(uncertain - after)
        checks += 1
    out = {"all_checks_pass": True, "groups_checked": checks,
           "result_sha256": sha(H / "资金费门大柱捕捉诊断.json"),
           "detail_sha256": sha(H / "资金费门大柱捕捉事后明细.csv"),
           "audit_sha256": sha(Path(__file__))}
    (H / "资金费门大柱捕捉独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
