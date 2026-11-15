"""Apply the previously independent scalar wallet audit to the new frozen gate."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
R85 = P / '第八十五轮_共享资金条件模拟'
R86 = P / '第八十六轮_首秒追价距离过滤'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for key, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][key]
    scalar_path = R85 / 'audit_wallet.py'
    assert sha(scalar_path) == frozen['sources_sha256']['r85_audit_code']
    spec = importlib.util.spec_from_file_location('ext87_old_scalar_audit', scalar_path)
    base = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = base
    spec.loader.exec_module(base)
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        gates = {(x['period'], x['observation_id'], x['variant']): x for x in csv.DictReader(f)}
    assert len(gates) == 226

    def load_extended(meta):
        records = base.load_inputs(meta)
        for r in records:
            key = (r['period'], r['obs'], f"one_observation_2r_{r['lev']}x")
            x = gates[key]
            assert x['extension_gate'] in ('True', 'False', '') and x['both'] in ('True', 'False', '')
            r['extension_gate'] = x['extension_gate'] == 'True'
            r['both'] = x['both'] == 'True'
        return records

    source = scalar_path.read_text(encoding='utf-8')
    replacements = [
        ('共享钱包情景汇总.json', '首秒距离钱包情景汇总.json'),
        ('共享钱包情景逐笔.csv', '首秒距离钱包情景逐笔.csv'),
        ('共享钱包事件账本.csv', '首秒距离钱包事件账本.csv'),
        ('共享钱包独立核验.json', '首秒距离钱包独立核验.json'),
        ("sha(H / 'run_wallet.py')", "sha(H / 'run_extension_wallet.py')"),
        ("sha(H / 'wallet_simulator.py')", "sha(R85 / 'wallet_simulator.py')"),
        ("sha(H / '钱包时序合成核验.json')", "sha(R85 / '钱包时序合成核验.json')"),
        ("(cohort == 'base' or r['oi'])", "r[cohort]"),
    ]
    for old, new in replacements:
        assert source.count(old) >= 1, old
        source = source.replace(old, new)
    scope = {'__file__': str(scalar_path), '__name__': 'ext87_independent_scalar'}
    exec(compile(source, str(scalar_path), 'exec'), scope)
    scope['H'], scope['R85'], scope['load_inputs'] = H, R85, load_extended
    scope['main']()
    path = H / '首秒距离钱包独立核验.json'
    out = json.loads(path.read_text(encoding='utf-8'))
    assert out['all_checks_pass'] and out['result_sha256'] == sha(H / '首秒距离钱包情景汇总.json')
    assert out['code_sha256'] == frozen['sources_sha256']['r85_audit_code']
    out['wrapper_code_sha256'] = sha(Path(__file__))
    out['adapted_code_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    out['gate_source_sha256'] = sha(R86 / '首秒距离逐笔.csv')
    out['note'] = 'Previously independent scalar wallet audit adapted only for the frozen gate and file paths; unknowns and floating PnL excluded.'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT87_INDEPENDENT_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
