"""Independently check cross-period paired metrics and their inputs."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import replay_cross as replay

H, P = replay.H, replay.P
R106 = P / "第一百零六轮_一秒五秒分层入场"
spec = importlib.util.spec_from_file_location("ext113_summary_oldstages", R106 / "run_staged.py")
oldstages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oldstages)


def main():
    replay.bulk.runner.guard(start=True)
    report = json.loads((H / "跨期跟踪退出配对结果.json").read_text(encoding="utf-8"))
    assert report["detail_sha256"] == replay.bulk.sha(H / "跨期跟踪退出配对明细.csv")
    assert report["code_sha256"] == replay.bulk.sha(H / "summarize_cross.py")
    details = pd.read_csv(H / "跨期跟踪退出配对明细.csv", dtype={"year": str})
    count = 0
    for year in ("2024", "2026"):
        _, _, base, _, one, _, _ = oldstages.load_year(year)
        data = json.loads((H / f"{year}跟踪退出风险账本.json").read_text(encoding="utf-8"))
        trail = {(x["observation_id"], x["variant"]): x for x in data["records"]}
        for row in [x for x in report["rows"] if x["year"] == year]:
            lev = row["leverage"]
            subset = details[(details.year == year) & (details.leverage == lev)]
            variant = f"one_observation_2r_{lev}x"
            selected = []
            for obs in subset.observation_id:
                key = (obs, variant)
                selected.append(base[key] if row["rule"] == "original_2r" else
                                one[(obs, variant.replace("_2r_", "_1r_"))] if row["rule"] == "one_r" else trail[key])
            assert len(selected) == row["trades"]
            frame = pd.DataFrame(selected)
            slip = row["exit_slippage_pct"] / 100
            fill = frame.exit_raw * (1 - frame.side * slip)
            net = frame.side * (fill - frame.entry_fill) / frame.entry_fill - .0005 * (1 + fill / frame.entry_fill) - frame.funding
            assert int((net > 0).sum()) == row["wins"]
            assert abs(100 * (net > 0).mean() - row["win_rate_pct"]) < 1e-10
            assert abs(100 * net.mean() - row["mean_net_pct_notional"]) < 1e-10
            if (net < 0).any():
                assert abs(net[net > 0].sum() / -net[net < 0].sum() - row["profit_factor"]) < 1e-10
            count += len(selected)
    out = {"all_checks_pass": True, "groups_checked": len(report["rows"]), "path_group_recalculations": count,
           "summary_sha256": replay.bulk.sha(H / "跨期跟踪退出配对结果.json"), "code_sha256": replay.bulk.sha(Path(__file__))}
    (H / "跨期跟踪退出汇总独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
