import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    path = H / '两次数据修复敏感性.json'
    x = json.loads(path.read_text(encoding='utf-8'))
    assert x['code_sha256'] == sha(H / 'combined_sensitivity.py')
    assert x['bnb_audit_sha256'] == sha(H / 'BNB独立核验.json')
    assert x['xrp_audit_sha256'] == sha(P / '第八十轮_未知候选一秒复核/单例一秒独立核验.json')
    sources = {'base': P / '第八十一轮_八至十月一秒观察/四时段等名义合并.json',
               'oi_gate': P / '第八十二轮_八至十月持仓量过滤/四时段持仓量合并.json'}
    assert x['base_summary_sha256'] == sha(sources['base']) and x['oi_summary_sha256'] == sha(sources['oi_gate'])
    assert len(x['rows']) == 4
    for row in x['rows']:
        src = next(r for r in json.loads(sources[row['cohort']].read_text(encoding='utf-8'))['rows'] if r['leverage'] == row['leverage'])
        for key in ('known_trades', 'net_wins', 'net_win_rate_pct', 'mean_net_pct_notional'):
            assert row[key] == src[key]
        assert row['original_unknown'] == src['unknown_candidates'] == row['sensitivity_unknown'] + 2
        assert row['original_no_order'] == src['known_no_order'] == row['sensitivity_no_order'] - 2
        expected = 100 * (row['net_wins'] + row['sensitivity_unknown']) / (row['known_trades'] + row['sensitivity_unknown'])
        assert math.isclose(row['sensitivity_optimistic_pct'], expected, rel_tol=1e-12)
        assert row['known_trades'] + row['sensitivity_unknown'] + row['sensitivity_no_order'] == 361
    out = {'all_checks_pass': True, 'groups_checked': len(x['rows']), 'result_sha256': sha(path),
           'code_sha256': sha(Path(__file__)), 'note': 'No-order repair arithmetic only; original results unchanged.'}
    (H / '修复敏感性独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_SENSITIVITY_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
