from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

from split_math import leg_net, half_and_half

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    a = {"entry_ts": 1, "entry_fill": "100", "exit_raw": "101", "side": 1, "funding": ".001"}
    b = {**a, "exit_raw": "102", "funding": ".002"}
    value = half_and_half(a, b, D(".0005"))
    exit_a, exit_b = D("101") * D(".9995"), D("102") * D(".9995")
    independent = (D(".5") * (exit_a - 100) + D(".5") * (exit_b - 100)) / 100
    independent -= D(".0005") + D(".0005") * (exit_a + exit_b) / D(200)
    independent -= D(".5") * D(".001") + D(".5") * D(".002")
    assert abs(value - independent) < D("1e-24")
    assert half_and_half(a, a, D(".0005")) == leg_net(a, D(".0005"))
    short1 = {**a, "side": -1, "exit_raw": "99"}
    short2 = {**short1, "exit_raw": "98"}
    assert half_and_half(short1, short2, D(".001")) < half_and_half(short1, short2, D(".0005"))
    try:
        half_and_half(a, {**b, "entry_ts": 2}, D(".0005"))
        raise AssertionError("different entries accepted")
    except AssertionError as exc:
        assert str(exc) != "different entries accepted"
    result = {"all_checks_pass": True, "code_sha256": sha(H / "split_math.py"), "test_sha256": sha(Path(__file__)),
              "cases": ["one entry fee", "both exit fees", "leg-specific funding", "long short slippage", "matched entry"]}
    (H / "分批算术合成核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
