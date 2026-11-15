"""Count two independently verified no-order data repairs without changing ledgers."""
import csv
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R80 = P / '第八十轮_未知候选一秒复核'
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
BNB = 'opening|BNBUSDT|1787213700000'
XRP = 'opening|XRPUSDT|1712564100000'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    b = json.loads((H / 'BNB独立核验.json').read_text(encoding='utf-8'))
    x = json.loads((R80 / '单例一秒独立核验.json').read_text(encoding='utf-8'))
    assert b['all_checks_pass'] and b['observation_id'] == BNB and b['source_result_sha256'] == sha(H / '三个候选来源复核.json')
    assert x['all_checks_pass'] and x['candidate_observation_id'] == XRP and x['result_sha256'] == sha(R80 / '单例一秒复核结果.json')
    with (R81 / '八至十月候选状态与账本.csv').open(encoding='utf-8', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['observation_id'] == BNB]
    assert len(rows) == 2 and all(r['category'] == 'unknown' for r in rows)
    old_audit = json.loads((R81 / '四时段合并独立核验.json').read_text(encoding='utf-8'))
    oi_audit = json.loads((R82 / '四时段持仓量合并独立核验.json').read_text(encoding='utf-8'))
    assert old_audit['all_checks_pass'] and old_audit['result_sha256'] == sha(R81 / '四时段等名义合并.json')
    assert oi_audit['all_checks_pass'] and oi_audit['result_sha256'] == sha(R82 / '四时段持仓量合并.json')
    output = []
    for cohort, file in (('base', R81 / '四时段等名义合并.json'), ('oi_gate', R82 / '四时段持仓量合并.json')):
        for old in json.loads(file.read_text(encoding='utf-8'))['rows']:
            assert old['unknown_candidates'] == 42
            new_unknown = old['unknown_candidates'] - 2
            result = {'cohort': cohort, 'leverage': old['leverage'], 'known_trades': old['known_trades'],
                      'net_wins': old['net_wins'], 'net_win_rate_pct': old['net_win_rate_pct'],
                      'mean_net_pct_notional': old['mean_net_pct_notional'],
                      'original_unknown': old['unknown_candidates'], 'sensitivity_unknown': new_unknown,
                      'original_no_order': old['known_no_order'], 'sensitivity_no_order': old['known_no_order'] + 2,
                      'original_optimistic_pct': old['optimistic_win_rate_pct'],
                      'sensitivity_optimistic_pct': 100 * (old['net_wins'] + new_unknown) / (old['known_trades'] + new_unknown)}
            assert result['known_trades'] + new_unknown + result['sensitivity_no_order'] == 361
            output.append(result)
    out = {'rows': output, 'bnb_audit_sha256': sha(H / 'BNB独立核验.json'), 'xrp_audit_sha256': sha(R80 / '单例一秒独立核验.json'),
           'base_summary_sha256': sha(R81 / '四时段等名义合并.json'), 'oi_summary_sha256': sha(R82 / '四时段持仓量合并.json'),
           'code_sha256': sha(Path(__file__)),
           'note': 'Only a sensitivity: two sources repaired as no-order; all other candidate statuses and frozen results unchanged.'}
    (H / '两次数据修复敏感性.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_SENSITIVITY', json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
