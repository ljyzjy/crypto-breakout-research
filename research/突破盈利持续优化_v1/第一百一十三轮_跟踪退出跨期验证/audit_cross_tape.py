"""Re-download fixed sample archives and independently replay trailing logic."""
from decimal import Decimal as D
import json
from pathlib import Path
import sys

import pandas as pd
import replay_cross as replay

H = Path(__file__).resolve().parent
sys.path.insert(0, str(replay.R112))
import audit_trailing_logic as independent


def near(a, b):
    return abs(D(str(a)) - D(str(b))) <= D("1e-9")


def main(year):
    replay.bulk.runner.guard(start=True)
    tasks, ref = replay.frozen(year)
    fp = replay.identity(year)
    selected = set(ref["sample_ids"])
    checked, observations = 0, set()
    for task in tasks:
        events = [e for e in task["events"] if e["observation_id"] in selected]
        if not events:
            continue
        cp_path = replay.cp_path(year, fp, task)
        assert cp_path.exists()
        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        assert cp["fingerprint"] == fp and cp["status"] == "verified"
        saved = {x["observation_id"]: x for x in cp["rows"]}
        for event in events:
            obs = event["observation_id"]
            blocks = []
            for expected in task["archives"]:
                replay.bulk.runner.guard()
                got, meta = replay.previous.public.fetch(task["contract"], expected["day"],
                    {obs: (event["trigger_minute"], event["quarter_end"] + 60000)}, replay.bulk.runner.guard)
                assert meta["sha256"] == expected["sha256"] and meta["bytes"] == expected["bytes"]
                blocks.extend(got[obs])
            assert blocks
            tape = pd.concat(blocks, ignore_index=True).sort_values(["transact_time", "agg_trade_id"], kind="mergesort")
            seq = [(int(t), int(i), D(str(p))) for t, i, p in zip(tape.transact_time, tape.agg_trade_id, tape.price)]
            for variant, old in event["old_paths"].items():
                want = saved[obs]["paths"][variant]
                action, reason, target, fill = independent.evaluate({**old, "side": event["side"]}, seq)
                assert (want["trailing_action"], want["trailing_reason"]) == (action, reason)
                if action == "trailing_exit":
                    assert int(want["exit_signal_ts"]) == target[0] and int(want["exit_ts"]) == fill[0]
                    assert near(want["exit_raw"], fill[2])
                    assert near(want["exit_fill"], fill[2] * (1 - D(int(event["side"])) * D(".0005")))
                elif action == "original":
                    assert int(want["exit_ts"]) == int(old["exit_ts"]) and near(want["exit_fill"], old["exit_fill"])
                else:
                    assert want["status"] == "trailing_path_unknown"
                checked += 1
            observations.add(obs)
            print("EXT113_TAPE_AUDIT", year, len(observations), "/", len(selected), flush=True)
    assert observations == selected
    out = {"all_checks_pass": True, "year": year, "sample_observations": len(observations), "sample_paths": checked,
           "sample_ids": sorted(observations), "replay_fingerprint": fp, "frozen_sha256": replay.bulk.sha(H / "输入冻结.json"),
           "audit_code_sha256": replay.bulk.sha(Path(__file__)), "logic_sha256": replay.bulk.sha(replay.R112 / "audit_trailing_logic.py"),
           "note": "Fresh full-archive SHA and independent scalar decision; original source parser shared."}
    (H / f"{year}跟踪退出逐笔独立样本核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT113_TAPE_AUDIT_PASS", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in ("2024", "2026")
    main(sys.argv[1])
