import csv
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    summary = json.loads((H / '延长钱包情景汇总.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '延长钱包独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '延长钱包情景汇总.json')
    assert summary['outcomes_sha256'] == sha(H / '延长钱包情景逐笔.csv')
    with (H / '延长钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        all_ = list(csv.DictReader(f))
    rows = []
    for s in summary['rows']:
        chosen = [x for x in all_ if x['cohort'] == s['cohort'] and int(x['leverage']) == s['leverage'] and
                  x['period'] == s['period'] and x['reverse_ties'] == str(s['reverse_ties']) and x['status'] == 'closed']
        assert len(chosen) == s['simulated_trades']
        losses = [x for x in chosen if float(x['net_pnl']) < 0]
        rows.append({'cohort': s['cohort'], 'leverage': s['leverage'], 'period': s['period'], 'reverse_ties': s['reverse_ties'],
                     'simulated_trades': len(chosen), 'losses': len(losses),
                     'losses_over_planned_risk': sum(float(x['net_pnl']) < -float(x['planned_risk']) for x in losses),
                     'losses_over_half_pct_reference_wallet': sum(float(x['net_pnl']) < -.005 * float(x['reference_wallet']) for x in losses),
                     'worst_pnl_pct_reference_wallet': min((100 * float(x['net_pnl']) / float(x['reference_wallet']) for x in losses), default=None)})
    out = {'all_checks_pass': True, 'groups_checked': len(rows), 'rows': rows, 'detail_sha256': sha(H / '延长钱包情景逐笔.csv'),
           'wallet_audit_sha256': sha(H / '延长钱包独立核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Planned stop risk is not a guaranteed loss limit; only verified paths included.'}
    (H / '延长钱包风险预算核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in rows:
        if r['period'] == 'linked' and r['leverage'] == 20 and not r['reverse_ties']:
            print('EXT89_BUDGET', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
