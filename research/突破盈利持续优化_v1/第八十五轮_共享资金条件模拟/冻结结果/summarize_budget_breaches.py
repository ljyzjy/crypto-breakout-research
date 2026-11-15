import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
D = Decimal


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '共享钱包独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    summary = json.loads((H / '共享钱包情景汇总.json').read_text(encoding='utf-8'))
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        all_rows = list(csv.DictReader(f))
    output = []
    for s in summary['rows']:
        selected = [x for x in all_rows if x['cohort'] == s['cohort'] and int(x['leverage']) == s['leverage'] and
                    x['period'] == s['period'] and x['reverse_ties'] == str(s['reverse_ties']) and x['status'] == 'closed']
        assert len(selected) == s['simulated_trades']
        losses = [x for x in selected if D(x['net_pnl']) < 0]
        worse_planned = [x for x in losses if D(x['net_pnl']) < -D(x['planned_risk'])]
        over_half = [x for x in losses if D(x['net_pnl']) < -D('.005') * D(x['reference_wallet'])]
        worst = min((D(100) * D(x['net_pnl']) / D(x['reference_wallet']) for x in losses), default=None)
        output.append({'cohort': s['cohort'], 'leverage': s['leverage'], 'period': s['period'], 'reverse_ties': s['reverse_ties'],
                       'simulated_trades': len(selected), 'losses': len(losses), 'losses_over_planned_risk': len(worse_planned),
                       'losses_over_half_pct_reference_wallet': len(over_half),
                       'worst_pnl_pct_reference_wallet': float(worst) if worst is not None else None})
    out = {'rows': output, 'summary_sha256': sha(H / '共享钱包情景汇总.json'), 'audit_sha256': sha(H / '共享钱包独立核验.json'),
           'detail_sha256': sha(H / '共享钱包情景逐笔.csv'), 'code_sha256': sha(Path(__file__)),
           'note': 'Risk budget is an estimate; actual model losses can exceed it. Not a guaranteed account loss limit.'}
    (H / '风险预算超限统计.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in output:
        if r['period'] == 'linked' and r['leverage'] == 20 and not r['reverse_ties']:
            print('EXT85_BUDGET', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
