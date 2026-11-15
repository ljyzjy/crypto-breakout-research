import importlib.util
import json
from decimal import Decimal as D
from pathlib import Path

from run_staged import H, sha
from wallet_engine_param import simulate


def record(obs, exit_fill="98.9505"):
    entry, out = D("100.05"), D(exit_fill)
    net = (out-entry)/entry-D(".0005")-D(".0005")*out/entry
    return {"observation_id": obs, "side": 1, "decision_ts": 0, "reference_ts": 1000,
            "reference": "100", "stop": "99", "entry_ts": 2000, "entry_fill": str(entry),
            "exit_signal_ts": 4000, "exit_ts": 9000, "exit_fill": str(out),
            "unit_net": str(net), "funding_events": []}


def main():
    source = H.parent / "第八十五轮_共享资金条件模拟" / "wallet_simulator.py"
    spec = importlib.util.spec_from_file_location("existing_wallet", source)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    records = [record("a"), record("b"), record("c")]
    assert simulate(records, 20) == original.simulate(records, 20)
    s, out, journal = simulate(records, 20, per_trade=D(".0025"), total_risk=D(".005"))
    assert s["simulated_trades"] == 2 and s["rejected_signals"] == 1
    assert s["maximum_open_positions"] == 2
    assert all(j["planned_open_risk"] <= D(5) + D("1e-12") for j in journal)
    assert abs(out["a"]["planned_risk"] - D("2.5")) < D("1e-12")
    changed = [record("a", "100.2"), record("b"), record("c")]
    _, out_changed, _ = simulate(changed, 20, per_trade=D(".0025"), total_risk=D(".005"))
    assert out["a"]["quantity"] == out_changed["a"]["quantity"]
    result = {"all_checks_pass": True, "engine_sha256": sha(H / "wallet_engine_param.py"),
              "original_engine_sha256": sha(source), "test_code_sha256": sha(Path(__file__)),
              "cases": ["original budget parity", "planned risk bounds", "same-time allocation", "future exit does not alter entry size"]}
    (H / "钱包参数合成核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
