from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

from wallet_simulator import simulate

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def record(obs, entry='100.05', exit_='100.9495', funding=None):
    events = funding or []
    charges = sum((D(str(x['charge'])) for x in events), D(0))
    entry, exit_ = D(entry), D(exit_)
    unit_net = (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - charges
    return {'observation_id': obs, 'side': 1, 'reference': '100', 'stop': '99',
            'decision_ts': 0, 'reference_ts': 1000, 'entry_ts': 2000, 'entry_fill': str(entry),
            'exit_signal_ts': 5000, 'exit_ts': 10000, 'exit_fill': str(exit_),
            'funding_events': events, 'unit_net': str(unit_net)}


def main():
    one = record('A', funding=[{'settlement_ts': 2000, 'charge': '0.0001'}, {'settlement_ts': 10000, 'charge': '0.0002'}])
    a, outcome, journal = simulate([one], 20)
    assert a['simulated_trades'] == 1 and outcome['A']['status'] == 'closed'
    assert sum(x['event'] == 'funding' for x in journal) == 2
    assert [x['event'] for x in journal] == ['reference', 'entry', 'funding', 'funding', 'exit']
    assert a['net_pnl'] > 0 and abs(outcome['A']['planned_risk'] - D('5')) < D('1e-25')
    b, three, _ = simulate([record('A'), record('B'), record('C')], 20)
    assert b['simulated_trades'] == 2 and three['C']['status'] == 'signal_rejected_budget_or_funds'
    _, reversed_, _ = simulate([record('A'), record('B'), record('C')], 20, reverse_ties=True)
    assert reversed_['A']['status'] == 'signal_rejected_budget_or_funds' and reversed_['C']['status'] == 'closed'
    gap = record('gap', entry='100000', exit_='99999')
    c, rejected, _ = simulate([gap], 10)
    assert rejected['gap']['status'] == 'entry_rejected_insufficient_margin' and c['final_wallet'] == D('1000')
    x = record('A', exit_='100.9495')
    y = record('A', exit_='110')
    _, xo, _ = simulate([x], 10)
    _, yo, _ = simulate([y], 10)
    assert xo['A']['quantity'] == yo['A']['quantity']
    out = {'all_checks_pass': True, 'tests': ['entry_and_exit_boundary_funding', 'cash_and_fee_reconciliation',
           'combined_stop_risk_cap', 'same_ms_signal_order', 'fill_gap_insufficient_margin', 'future_exit_perturbation'],
           'engine_sha256': sha(H / 'wallet_simulator.py'), 'test_code_sha256': sha(Path(__file__))}
    (H / '钱包时序合成核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT85_SYNTHETIC_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
