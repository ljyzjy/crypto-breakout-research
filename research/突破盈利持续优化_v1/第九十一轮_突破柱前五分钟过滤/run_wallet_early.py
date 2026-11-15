"""Conditional 2022 shared-wallet simulation for the frozen early gate."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
R85 = H.parent / '第八十五轮_共享资金条件模拟'
sys.path.insert(0, str(R90)); import run_wallet_2022 as base
sys.path.insert(0, str(R85)); from wallet_simulator import simulate


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def load_records():
    detail = pd.read_csv(H / '前五分钟过滤逐笔.csv', dtype=str, keep_default_na=False)
    early = {(x['observation_id'], x['holding_rule'], int(x['leverage'])): x['early'] == 'True'
             for x in detail[detail.period.eq('2022')].to_dict('records')}
    result = []
    for r in base.load_records():
        key = r['observation_id'], r['period'], r['leverage']
        assert key in early and early[key] == (r['decision_ts'] % 900000 < 300000)
        if early[key]: result.append(r)
    return result


def main():
    base.runner.guard(start=True)
    audit = json.loads((H / '前五分钟过滤独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '前五分钟过滤对照.json')
    assert audit['detail_sha256'] == sha(H / '前五分钟过滤逐笔.csv')
    test = json.loads((R85 / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(R85 / 'wallet_simulator.py')
    records = load_records()
    summaries, outcomes, journals = [], [], []
    for cohort in ('base', 'distance', 'oi', 'oi_distance'):
      for lev in (10, 20):
       for period in ('original', 'extended'):
        selected = [r for r in records if r['leverage'] == lev and r['period'] == period and r[cohort]]
        for reverse in (False, True):
            summary, rows, journal = simulate(selected, lev, reverse_ties=reverse)
            extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
            summaries.append({**extra, **{k: float(v) if isinstance(v, Decimal) else v for k, v in summary.items()}})
            for obs, value in rows.items():
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
    out = {'rows': summaries, 'outcomes_sha256': sha(H / '共享钱包情景逐笔.csv'),
           'journal_sha256': sha(H / '共享钱包事件账本.csv'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'test_sha256': sha(R85 / '钱包时序合成核验.json'), 'engine_sha256': sha(R85 / 'wallet_simulator.py'),
           'code_sha256': sha(Path(__file__)), 'unknown_2022_rank_hours': 240,
           'note': '2022 known paths only; unrankable hours and unknown candidates omitted; no floating equity.'}
    (H / '共享钱包情景汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT91_WALLET', json.dumps([x for x in summaries if x['leverage'] == 20 and not x['reverse_ties']], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
