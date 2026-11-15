import hashlib
import json
from pathlib import Path
from decimal import Decimal as D
from one_second_check import first_second

H = Path(__file__).resolve().parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    def trade(ts, i, p, q, maker):
        return (ts, i, D(p), D(q), maker)
    agg = [trade(0, 1, '100', '1', 'false'), trade(100, 2, '101', '1', 'false'),
           trade(101, 3, '101', '2', 'false'), trade(200, 4, '101', '1', 'false'),
           trade(1099, 5, '101', '1', 'true'), trade(1100, 6, '101', '1', 'false')]
    same = list(agg)
    result = first_second(agg, same, 0, D('100'), D('90'), True, False)
    assert result['status'] == 'qualified_requires_path' and result['aggregate_count'] == 3
    assert result['buy'] == '303' and result['sell'] == '101' and result['reference_ts'] == 1100
    assert first_second(agg, same, 0, D('100'), D('90'), False, False)['status'] == 'known_no_order_direction'
    x = list(same)
    x[2] = trade(101, 3, '101', '3', 'false')
    assert first_second(agg, x, 0, D('100'), D('90'), True, False)['status'] == 'unknown_flow'
    x = list(same)
    x[-1] = trade(1100, 6, '100', '1', 'false')
    assert first_second(agg, x, 0, D('100'), D('90'), True, False)['status'] == 'unknown_reference'
    x = [trade(0, 1, '100', '1', 'false'), trade(100, 2, '101', '1', 'false'),
         trade(200, 3, '101', '1', 'false'), trade(1100, 4, '101', '1', 'false')]
    assert first_second(x, x, 0, D('100'), D('90'), True, False)['status'] == 'known_no_order_flow'
    out = {'all_checks_pass': True, 'checks': ['strict_first_second', 'aggregate_count', 'direction', 'flow_disagreement', 'reference_disagreement'],
           'code_sha256': sha(H / 'one_second_check.py'), 'test_sha256': sha(Path(__file__))}
    (H / '首秒边界测试.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('UNKNOWN_ONESEC_TEST', out, flush=True)


if __name__ == '__main__':
    main()
