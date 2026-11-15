import csv
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result = json.loads((H / '首秒距离钱包情景汇总.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '首秒距离钱包独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '首秒距离钱包情景汇总.json')
    assert result['outcomes_sha256'] == sha(H / '首秒距离钱包情景逐笔.csv')
    with (H / '首秒距离钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        data = list(csv.DictReader(f))
    rows = []
    for scenario in result['rows']:
        chosen = [r for r in data if r['cohort'] == scenario['cohort'] and int(r['leverage']) == scenario['leverage'] and
                  r['period'] == scenario['period'] and r['reverse_ties'] == str(scenario['reverse_ties']) and r['status'] == 'closed']
        assert len(chosen) == scenario['simulated_trades']
        losses = [r for r in chosen if float(r['net_pnl']) < 0]
        worst = min((100 * float(r['net_pnl']) / float(r['reference_wallet']) for r in losses), default=None)
        rows.append({'cohort': scenario['cohort'], 'leverage': scenario['leverage'], 'period': scenario['period'],
                     'reverse_ties': scenario['reverse_ties'], 'simulated_trades': len(chosen), 'losses': len(losses),
                     'losses_over_planned_risk': sum(float(r['net_pnl']) < -float(r['planned_risk']) for r in losses),
                     'losses_over_half_pct_reference_wallet': sum(float(r['net_pnl']) < -.005 * float(r['reference_wallet']) for r in losses),
                     'worst_pnl_pct_reference_wallet': worst})
    out = {'all_checks_pass': True, 'groups_checked': len(rows), 'rows': rows,
           'detail_sha256': sha(H / '首秒距离钱包情景逐笔.csv'), 'wallet_audit_sha256': sha(H / '首秒距离钱包独立核验.json'),
           'code_sha256': sha(Path(__file__)), 'note': 'Counts of model losses above planned risk, not a loss guarantee.'}
    (H / '首秒距离风险预算核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in rows:
        if r['leverage'] == 20 and r['period'] == 'linked' and not r['reverse_ties']:
            print('EXT87_BUDGET', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
