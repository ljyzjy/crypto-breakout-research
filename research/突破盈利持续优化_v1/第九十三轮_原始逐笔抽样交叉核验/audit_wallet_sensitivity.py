"""Scalar event-by-event audit of wallets with sampled source conflicts excluded."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import wallet_sensitivity as wallet

H = Path(__file__).resolve().parent
R85 = H.parent / '第八十五轮_共享资金条件模拟'
SCALAR = R85 / 'audit_wallet.py'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def load_records(_):
    out = []
    for r in wallet.load_records():
        out.append({'period': r['period'], 'obs': r['observation_id'], 'lev': r['leverage'],
                    **{k: r[k] for k in ('base', 'distance', 'oi', 'oi_distance')},
                    'side': r['side'], 'reference_ts': r['reference_ts'], 'reference': Decimal(r['reference']),
                    'stop': Decimal(r['stop']), 'entry_ts': r['entry_ts'], 'entry': Decimal(r['entry_fill']),
                    'exit_ts': r['exit_ts'], 'exit': Decimal(r['exit_fill']), 'unit_net': Decimal(r['unit_net']),
                    'funding': r['funding_events']})
    return out


def main():
    wallet.original.runner.guard(start=True)
    text = SCALAR.read_text(encoding='utf-8')
    replacements = [("sha(H / 'run_wallet.py')", "sha(H / 'wallet_sensitivity.py')"),
                    ("sha(H / 'wallet_simulator.py')", "sha(R85 / 'wallet_simulator.py')"),
                    ("sha(H / '钱包时序合成核验.json')", "sha(R85 / '钱包时序合成核验.json')"),
                    ("frozen['sources_sha256'][key]", "frozen['source_sha256'][key]"),
                    ("(cohort == 'base' or r['oi'])", "r[cohort]"),
                    ("len(result['rows']) == 40", "len(result['rows']) == 64")]
    for a, b in replacements:
        assert text.count(a) >= 1, a
        text = text.replace(a, b)
    scope = {'__name__': 'ext93_independent_wallet', '__file__': str(SCALAR)}
    exec(compile(text, str(SCALAR), 'exec'), scope)
    scope.update({'H': H, 'R85': R85, 'load_inputs': load_records})
    scope['main']()
    path = H / '共享钱包独立核验.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['all_checks_pass'] and result['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    assert result['code_sha256'] == sha(SCALAR)
    result.update(wrapper_code_sha256=sha(Path(__file__)), adapted_code_sha256=hashlib.sha256(text.encode()).hexdigest(),
                  note='Scalar wallet audit after sample conflicts removed; all remaining unknowns and floating equity excluded.')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_WALLET_AUDIT', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
