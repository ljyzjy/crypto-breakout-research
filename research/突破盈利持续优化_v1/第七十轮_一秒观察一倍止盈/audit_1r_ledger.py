"""Independently recompute 1R costs, funding and mark-price proxy from ZIP CSVs."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile
import psutil

getcontext().prec = 40
D = Decimal
H = Path(__file__).resolve().parent
M = 60000


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def main(year):
    path = H / f'{year}一倍止盈本地风险账本.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['year'] == year and data['settlement_code_sha256'] == sha(H / 'settle_1r_local.py')
    records = [x for x in data['records'] if x.get('risk_status') == 'verified']
    assert len({(x['observation_id'], x['variant']) for x in records}) == len(records)
    archives = {(x['kind'], x['contract'], x['month']): x for x in data['risk_archives'] if x['status'] == 'verified'}
    cache, needed = {}, {}
    for row in records:
        for ts in range(int(row['entry_ts']) // M * M, int(row['exit_ts']) // M * M + M, M):
            mon = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')
            needed.setdefault((row['contract'], mon), set()).add(ts)

    def source(kind, contract, mon):
        key = (kind, contract, mon)
        if key in cache:
            return cache[key]
        if shutil.disk_usage(H).free < 2_200_000_000 or psutil.virtual_memory().available < 250 * 1024 ** 2:
            raise RuntimeError('resource_headroom')
        item = archives[key]
        p = Path(item['path'])
        assert sha(p) == item['sha256']
        result = {}
        with zipfile.ZipFile(p) as z:
            files = [i for i in z.infolist() if not i.is_dir()]
            assert len(files) == 1
            with z.open(files[0]) as raw:
                for row in csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')):
                    ts = int(row['open_time' if kind == 'markPriceKlines' else 'calc_time'])
                    if kind == 'markPriceKlines' and ts not in needed[(contract, mon)]:
                        continue
                    assert ts not in result
                    if kind == 'markPriceKlines':
                        result[ts] = {n: D(row[n]) for n in ('open', 'high', 'low', 'close')}
                    else:
                        result[ts] = {'interval': D(row['funding_interval_hours']), 'rate': D(row['last_funding_rate'])}
        cache[key] = result
        return result

    checked = 0
    worst_error = D(0)
    for row in records:
        side = int(row['side'])
        lev = int(row['variant'].rsplit('_', 1)[1].rstrip('x'))
        entry_ts, exit_ts = int(row['entry_ts']), int(row['exit_ts'])
        assert int(row['entry_signal_reference_ts']) >= int(row['decision_ts']) + 1000
        assert entry_ts >= int(row['entry_signal_reference_ts']) + 1000
        assert exit_ts >= int(row['exit_signal_ts']) + 5000
        entry = D(str(row['entry_raw'])) * (D(1) + D(side) * D('.0005'))
        exit_ = D(str(row['exit_raw'])) * (D(1) - D(side) * D('.0005'))
        assert near(entry, row['entry_fill']) and near(exit_, row['exit_fill'])
        qty, funding, extremes, events = D(1) / entry, D(0), [], []
        for ts in range(entry_ts // M * M, exit_ts // M * M + M, M):
            mon = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')
            mark = source('markPriceKlines', row['contract'], mon)[ts]
            fund = source('fundingRate', row['contract'], mon)
            dates = sorted(fund)
            before = [t for t in dates if t <= ts]
            after = [t for t in dates if t > ts]
            left = before[-1] if before else dates[0]
            right = after[0] if after else dates[-1]
            allowance = max(fund[left]['interval'], fund[right]['interval']) * D(3600000) * D('1.5')
            gap = right - left if before and after else (ts - left if before else right - ts)
            assert D(gap) <= allowance
            extremes.append(mark['low'] if side == 1 else mark['high'])
            for ft, f in fund.items():
                if ft // M * M != ts or not entry_ts <= ft <= exit_ts:
                    continue
                amount = D(side) * qty * mark['open'] * f['rate']
                if ft in (entry_ts, exit_ts):
                    amount = max(D(0), amount)
                funding += amount
                events.append(ft)
        exit_fee = qty * exit_ * D('.0005')
        net = D(side) * qty * (exit_ - entry) - D('.0005') - exit_fee - funding
        proxy = any(D(1) / D(lev) - D('.0005') - max(funding, D(0)) + D(side) * qty * (v - entry) <= qty * v * D('.01') for v in extremes)
        assert near(funding, row['funding']) and near(exit_fee, row['exit_fee']) and near(net, row['net_per_unit_notional'])
        assert proxy == row['liq_proxy'] and sorted(events) == sorted(x['settlement_ts'] for x in json.loads(row['funding_events_json']))
        worst_error = max(worst_error, abs(net - D(str(row['net_per_unit_notional']))))
        checked += 1
    result = {'all_checks_pass': checked > 0, 'year': year, 'audited_paths': checked,
              'unknown_replay_paths': len(data['replay_unknown']),
              'unknown_risk_paths': sum(x.get('risk_status') != 'verified' for x in data['records']),
              'liquidation_proxy_paths': sum(bool(x['liq_proxy']) for x in records),
              'max_net_fraction_error': float(worst_error), 'ledger_sha256': sha(path),
              'audit_code_sha256': sha(Path(__file__)), 'note': 'Minute marks are proxies and do not reconstruct exchange liquidation.'}
    (H / f'{year}一倍止盈账本独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_LEDGER_AUDIT', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
