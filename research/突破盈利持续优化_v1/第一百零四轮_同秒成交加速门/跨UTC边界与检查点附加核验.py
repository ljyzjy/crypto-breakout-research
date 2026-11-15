"""Read-only verification of saved phase-count checkpoints and synthetic UTC boundary."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io
import json
import random
import zipfile

import pandas as pd
import count_same_phase as phase

H = Path(__file__).resolve().parent
ROOT = Path(r"D:\CodexResearch_2022_firstsec_20261115_v1")
CHECKPOINTS = ROOT / "same_phase_2022_checkpoints"
R98 = H.parent / "第九十八轮_二零二二原始逐笔全样本"
DAY, Q = 86_400_000, 900_000


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def memory_zip(times):
    rows = "id,price,qty,quote_qty,time,is_buyer_maker\n" + "".join(
        f"{i},1.0,1.0,1.0,{t},true\n" for i, t in enumerate(times))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("test.csv", rows)
    buffer.seek(0)
    return buffer


def cross_utc_test():
    t = int(datetime(2022, 8, 14, 0, 0, 0, 500_000, tzinfo=timezone.utc).timestamp() * 1000)
    windows = [(t - j * Q, t - j * Q + 1000) for j in range(1, 21)] + [(t, t + 1000)]
    records = []
    for index, (start, end) in enumerate(windows):
        # Repeated millisecond timestamps must count as separate raw trade records.
        records.extend([start, start + 1, start + 1, end])
        if index == 20:
            records.append(start + 999)
    records.extend([t + 1001, t + 70_000])
    random.Random(42).shuffle(records)
    shards = defaultdict(list)
    for timestamp in records:
        shards[timestamp // DAY].append(timestamp)
    assert len(shards) == 2
    counts = [0] * 21
    for part in shards.values():
        result = phase.count_windows(memory_zip(part), windows)
        counts = [a + b for a, b in zip(counts, result)]
    assert counts[:-1] == [2] * 20 and counts[-1] == 3
    p, n = sum(counts[:-1]), counts[-1]
    assert p == 40 and n == 3 and 40 * n == 3 * p
    assert 40 * n >= 3 * p and not (40 * n >= 3 * (p + 1))
    changed = dict(shards)
    changed[t // DAY] = list(changed[t // DAY]) + [t + 5000, t + 8000]
    recalculated = [0] * 21
    for part in changed.values():
        result = phase.count_windows(memory_zip(part), windows)
        recalculated = [a + b for a, b in zip(recalculated, result)]
    assert recalculated == counts
    return {"all_checks_pass": True, "cases": ["UTC midnight shard aggregation", "strict endpoints",
        "multiple raw records at same millisecond", "exact 1.5x boundary", "future records ignored"]}


def main():
    freeze = json.loads((H / "研究冻结.json").read_text(encoding="utf-8"))
    for name, expected in freeze["sources"].items():
        assert sha(name) == expected, name
    expected_fp = hashlib.sha256((sha(H / "研究冻结.json") + sha(H / "count_same_phase.py")).encode()).hexdigest()
    assert phase.fingerprint() == expected_fp
    detail = pd.read_csv(R98 / "候选状态与单位账本.csv")
    ids = set(detail.loc[detail.category.eq("trade"), "observation_id"])
    signals = pd.read_parquet(R98 / "原始逐笔批次" / "逐笔信号.parquet")
    signals = signals[signals.observation_id.isin(ids)].set_index("observation_id")
    assert len(signals) == len(ids) == 133 and signals.index.is_unique
    files = sorted(CHECKPOINTS.glob("*.json"))
    seen, archive_info, statuses = set(), {}, Counter()
    for file in files:
        r = json.loads(file.read_text(encoding="utf-8"))
        obs = r["observation_id"]
        assert obs not in seen and obs in ids and r["fingerprint"] == expected_fp
        assert file.name == hashlib.sha256((expected_fp + "|" + obs).encode()).hexdigest() + ".json"
        row = signals.loc[obs]
        assert int(r["decision_ts"]) == int(row.decision_ts) and r["contract"] == row.contract
        statuses[r["status"]] += 1
        if r["status"] != "unknown_source":
            counts = r["previous_counts"]
            assert len(counts) == 20 and all(isinstance(n, int) and n >= 0 for n in counts)
            assert sum(counts) == r["previous_total"] and int(row.one_count) == r["stored_n"]
            if r["status"] == "verified":
                assert r["current_n"] == r["stored_n"] and r["previous_total"] > 0
                assert r["accepted"] == (40 * r["current_n"] >= 3 * r["previous_total"])
            elif r["status"] == "unknown_zero_history":
                assert r["previous_total"] == 0 and r["accepted"] is None
            elif r["status"] == "unknown_current_count_mismatch":
                assert r["current_n"] != r["stored_n"] and r["accepted"] is None
            else:
                raise AssertionError(r["status"])
        for a in r["archives"]:
            path = Path(a["path"])
            assert path.resolve().is_relative_to(ROOT.resolve()) and path.is_file()
            assert path.stat().st_size == a["bytes"]
            old = archive_info.setdefault(str(path), a)
            assert old["sha256"] == a["sha256"] and old["bytes"] == a["bytes"]
        seen.add(obs)
    selected = sorted(archive_info.values(), key=lambda x: (x["bytes"], x["path"]))[:3]
    for a in selected:
        assert sha(a["path"]) == a["sha256"]
    out = {"all_checks_pass": True, "checkpoint_count": len(files), "target_events": len(ids),
        "remaining_events": len(ids) - len(files), "checkpoint_statuses": dict(statuses),
        "unique_archives_referenced": len(archive_info), "sampled_archive_hashes": len(selected),
        "cross_utc_synthetic": cross_utc_test(), "frozen_sha256": sha(H / "研究冻结.json"),
        "count_code_sha256": sha(H / "count_same_phase.py"), "audit_code_sha256": sha(Path(__file__)),
        "note": "Checkpoint metadata and three smallest archived ZIP hashes only; no trade outcomes or full 133-event replay."}
    (H / "跨UTC边界与检查点附加核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
