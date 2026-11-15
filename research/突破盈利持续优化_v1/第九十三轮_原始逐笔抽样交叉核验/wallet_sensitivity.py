"""Recompute known-path wallets after excluding raw-vs-aggregate sample conflicts."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
R91 = H.parent / '第九十一轮_突破柱前五分钟过滤'
R85 = H.parent / '第八十五轮_共享资金条件模拟'
sys.path.insert(0, str(R90)); import run_wallet_2022 as original
sys.path.insert(0, str(R85)); from wallet_simulator import simulate


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def load_records():
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    records = []
    for r in original.load_records():
        if r['observation_id'] in affected: continue
        records.append({**r, 'period': r['period'] + '_all'})
        if r['decision_ts'] % 900000 < 300000:
            records.append({**r, 'period': r['period'] + '_early'})
    return records


def main():
    original.runner.guard(start=True)
    for path, target in [(H / '敏感性独立核验.json', H / '原始数据分歧敏感性.json'),
                         (H / '前五分钟敏感性独立核验.json', H / '前五分钟分歧敏感性.json'),
                         (R90 / '共享钱包独立核验.json', R90 / '共享钱包情景汇总.json'),
                         (R91 / '共享钱包独立核验.json', R91 / '共享钱包情景汇总.json')]:
        x = json.loads(path.read_text(encoding='utf-8')); assert x['all_checks_pass'] and x['result_sha256'] == sha(target)
    test = json.loads((R85 / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(R85 / 'wallet_simulator.py')
    records = load_records(); summaries, outcomes, journals = [], [], []
    for cohort in ('base', 'distance', 'oi', 'oi_distance'):
      for lev in (10, 20):
       for period in ('original_all', 'extended_all', 'original_early', 'extended_early'):
        selected = [r for r in records if r['leverage'] == lev and r['period'] == period and r[cohort]]
        for reverse in (False, True):
            summary, output, journal = simulate(selected, lev, reverse_ties=reverse)
            extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
            summaries.append({**extra, **{k: float(v) if isinstance(v, Decimal) else v for k, v in summary.items()}})
            for obs, value in output.items():
                outcomes.append({**extra, 'observation_id': obs, 'source_period': period,
                                 **{k: value.get(k) for k in ('status', 'quantity', 'net_pnl', 'planned_risk', 'reference_wallet',
                                                              'estimated_entry', 'margin', 'open_fee', 'funding_paid')}})
            journals.extend({**extra, **j} for j in journal)
    def write(path, rows):
        assert rows
        with path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write(H / '共享钱包情景逐笔.csv', outcomes)
    write(H / '共享钱包事件账本.csv', journals)
    result = {'rows': summaries, 'outcomes_sha256': sha(H / '共享钱包情景逐笔.csv'),
              'journal_sha256': sha(H / '共享钱包事件账本.csv'), 'frozen_sha256': sha(H / '冻结时点.json'),
              'test_sha256': sha(R85 / '钱包时序合成核验.json'), 'engine_sha256': sha(R85 / 'wallet_simulator.py'),
              'code_sha256': sha(Path(__file__)), 'unknown_2022_rank_hours': 240,
              'note': 'Known paths after sampled conflicts excluded; untested source ambiguity and floating equity remain.'}
    (H / '共享钱包情景汇总.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT93_WALLET', json.dumps([x for x in summaries if x['cohort'] == 'base' and x['leverage'] == 20 and not x['reverse_ties']], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
