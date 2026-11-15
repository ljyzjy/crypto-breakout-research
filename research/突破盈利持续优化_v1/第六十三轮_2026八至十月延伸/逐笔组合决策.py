"""Compose frozen original, single-retest and 1s/5s decision functions."""
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
for folder in ("第三十三轮_动态池逐笔执行", "第四十七轮_一次重新突破确认", "第五十一轮_缩短市价入场延迟"):
    sys.path.insert(0, str(P / folder))
import tape_decision
import retest_decision
import entry_1s


def decide(candidate, tape, bars):
    first = tape_decision.decide(candidate, tape, bars)
    chosen, origin = first, "original"
    if first.get("status") == "flow_filter_not_met":
        side, ref, level = int(first["side"]), float(first["raw_entry_5s"]), float(first["level"])
        if side * (ref - level) <= 0:
            chosen = retest_decision.decide({**candidate, **first}, tape)
            origin = "retest"
    paths5, paths1 = {}, {}
    if chosen.get("status") == "qualified":
        event = {**candidate, **chosen}
        for lev in (10, 20):
            name = f"normal_2r_{lev}x"
            if name not in chosen["paths"]:
                continue
            original = {**chosen["paths"][name], "variant": name}
            paths5[name] = original
            paths1[f"one_second_2r_{lev}x"] = entry_1s.decide(event, original, tape)
    chosen_clean = {k: v for k, v in chosen.items() if k != "paths"}
    first_clean = {k: v for k, v in first.items() if k != "paths"}
    return {"first": first_clean, "chosen": chosen_clean, "origin": origin,
            "paths_5s": paths5, "paths_1s": paths1}
