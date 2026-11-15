import csv
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    path = H / '风险预算超限统计.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'summarize_budget_breaches.py')
    assert result['detail_sha256'] == sha(H / '共享钱包情景逐笔.csv')
    assert result['summary_sha256'] == sha(H / '共享钱包情景汇总.json')
    assert result['audit_sha256'] == sha(H / '共享钱包独立核验.json')
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    for out in result['rows']:
        cases = [x for x in rows if x['cohort'] == out['cohort'] and int(x['leverage']) == out['leverage'] and
                 x['period'] == out['period'] and x['reverse_ties'] == str(out['reverse_ties']) and x['status'] == 'closed']
        losses = [x for x in cases if float(x['net_pnl']) < 0]
        assert len(cases) == out['simulated_trades'] and len(losses) == out['losses']
        assert out['losses_over_planned_risk'] == sum(float(x['net_pnl']) < -float(x['planned_risk']) for x in losses)
        assert out['losses_over_half_pct_reference_wallet'] == sum(float(x['net_pnl']) < -.005 * float(x['reference_wallet']) for x in losses)
        worst = min((100 * float(x['net_pnl']) / float(x['reference_wallet']) for x in losses), default=None)
        if worst is None:
            assert out['worst_pnl_pct_reference_wallet'] is None
        else:
            assert math.isclose(worst, out['worst_pnl_pct_reference_wallet'], rel_tol=1e-10, abs_tol=1e-10)
    audit = {'all_checks_pass': True, 'groups_checked': len(result['rows']), 'result_sha256': sha(path),
             'code_sha256': sha(Path(__file__)), 'note': 'Actual model PnL compared with signal-time planned loss, not a loss guarantee.'}
    (H / '风险预算超限独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT85_BUDGET_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
