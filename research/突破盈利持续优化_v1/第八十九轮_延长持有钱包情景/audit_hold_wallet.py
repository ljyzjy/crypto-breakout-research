"""Adapt the independent scalar wallet audit to verified extended paths."""
import csv
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
R85 = P / '第八十五轮_共享资金条件模拟'
R86 = P / '第八十六轮_首秒追价距离过滤'
R88 = P / '第八十八轮_延长一根柱持有'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for key, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][key]
    scalar = R85 / 'audit_wallet.py'
    assert sha(scalar) == frozen['sources_sha256']['r85_audit_code']
    spec = importlib.util.spec_from_file_location('ext89_original_scalar', scalar)
    base = importlib.util.module_from_spec(spec); sys.modules[spec.name] = base; spec.loader.exec_module(base)
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        gates = {(x['period'], x['observation_id'], x['variant']): x for x in csv.DictReader(f)}
    ledger = json.loads((R88 / '延长持有风险账本.json').read_text(encoding='utf-8'))
    updates = {(x['period'], x['observation_id'], x['variant']): x for x in ledger['records']}
    assert len(gates) == 226 and len(updates) == 68 and not ledger['unknown']

    def load_extended(meta):
        records = base.load_inputs(meta)
        for r in records:
            key = r['period'], r['obs'], f"one_observation_2r_{r['lev']}x"
            g = gates[key]
            assert g['oi_gate'] in ('True', 'False', '') and (g['oi_gate'] == 'True') == r['oi']
            r['base'] = True
            r['extension_gate'] = g['extension_gate'] == 'True'
            r['oi_gate'] = g['oi_gate'] == 'True'
            r['both'] = g['both'] == 'True'
            if key in updates:
                pair = updates[key]; new, risk = pair['extended'], pair['risk']
                assert new['status'] == risk['risk_status'] == 'verified' and not risk['liq_proxy']
                assert int(new['entry_ts']) == r['entry_ts'] and abs(Decimal(str(new['entry_fill'])) - r['entry']) < Decimal('1e-9')
                r['exit_ts'] = int(new['exit_ts'])
                r['exit'] = Decimal(str(new['exit_fill']))
                r['unit_net'] = Decimal(str(risk['net_per_unit_notional']))
                r['funding'] = json.loads(risk['funding_events_json'])
        return records

    source = scalar.read_text(encoding='utf-8')
    replacements = [
        ('共享钱包情景汇总.json', '延长钱包情景汇总.json'),
        ('共享钱包情景逐笔.csv', '延长钱包情景逐笔.csv'),
        ('共享钱包事件账本.csv', '延长钱包事件账本.csv'),
        ('共享钱包独立核验.json', '延长钱包独立核验.json'),
        ("sha(H / 'run_wallet.py')", "sha(H / 'run_hold_wallet.py')"),
        ("sha(H / 'wallet_simulator.py')", "sha(R85 / 'wallet_simulator.py')"),
        ("sha(H / '钱包时序合成核验.json')", "sha(R85 / '钱包时序合成核验.json')"),
        ("(cohort == 'base' or r['oi'])", "r[cohort]"),
        ("len(result['rows']) == 40", "len(result['rows']) == 80"),
    ]
    for old, new in replacements:
        assert source.count(old) >= 1, old
        source = source.replace(old, new)
    scope = {'__file__': str(scalar), '__name__': 'ext89_independent_scalar'}
    exec(compile(source, str(scalar), 'exec'), scope)
    scope['H'], scope['R85'], scope['load_inputs'] = H, R85, load_extended
    scope['main']()
    output = H / '延长钱包独立核验.json'
    out = json.loads(output.read_text(encoding='utf-8'))
    assert out['all_checks_pass'] and out['result_sha256'] == sha(H / '延长钱包情景汇总.json')
    assert out['code_sha256'] == frozen['sources_sha256']['r85_audit_code']
    out['wrapper_code_sha256'] = sha(Path(__file__))
    out['adapted_code_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    out['extended_ledger_sha256'] = sha(R88 / '延长持有风险账本.json')
    out['note'] = 'Previously independent scalar audit adapted to frozen extended paths; unknowns and floating equity excluded.'
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT89_INDEPENDENT_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
