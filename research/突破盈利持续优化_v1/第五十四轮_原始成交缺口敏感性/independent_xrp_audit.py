"""Independently check one preselected source discrepancy; never alter frozen ledgers."""
import csv, hashlib, io, json, math, shutil, sys, zipfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psutil, requests

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
FIXED = P / '第四十六轮_固定十一加密币跨时段'
RETEST = P / '第四十七轮_一次重新突破确认'
OLD = ROOT / 'work' / 'point_in_time_universe33' / 'raw_reconciliation' / '9705fef0a37efffac0bc8a9eb21281c9429df01cdc731bfe944c436d350d43a6.json'
OBS = 'opening|XRPUSDT|1712564100000'
START = 1712564100000
BASE = 'https://data.binance.vision/data/futures/um/daily/'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_reserve')
    if psutil.virtual_memory().available < 500 * 1024 * 1024:
        raise RuntimeError('memory_headroom')

def read_archive(kind, expected):
    guard()
    stem = 'XRPUSDT-1m-2024-04-08.zip' if kind == 'klines' else f'XRPUSDT-{kind}-2024-04-08.zip'
    suffix = f'klines/XRPUSDT/1m/{stem}' if kind == 'klines' else f'{kind}/XRPUSDT/{stem}'
    url = BASE + suffix
    with requests.Session() as s:
        c = s.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
        declared = c.text.strip().split()[0].lower()
        r = s.get(url, timeout=(15, 120)); r.raise_for_status()
        body = r.content
    actual = sha(body)
    if actual != declared or actual != expected['sha256'] or len(body) != expected['bytes']:
        raise ValueError('archive_sha_or_size_mismatch:' + kind)
    return body, {'kind': kind, 'url': url, 'bytes': len(body), 'sha256': actual}

def csv_rows(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('unexpected_zip_members')
        with z.open(names[0]) as raw:
            with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as stream:
                yield from csv.DictReader(stream)

def read_minute_bar(body):
    hits = [x for x in csv_rows(body) if int(x['open_time']) == START]
    if len(hits) != 1: raise ValueError('minute_bar_count')
    x = hits[0]
    def field(*keys):
        for k in keys:
            if k in x: return x[k]
        raise ValueError('missing_minute_field:' + str(keys))
    return {'open':Decimal(field('open')), 'high':Decimal(field('high')),
            'low':Decimal(field('low')), 'close':Decimal(field('close')),
            'volume':Decimal(field('volume')), 'quote_volume':Decimal(field('quote_volume','quote_asset_volume')),
            'count':int(field('count','number_of_trades','num_trades'))}

def read_window(body, kind):
    rows = []
    for n, x in enumerate(csv_rows(body), 1):
        if n % 100000 == 0: guard()
        when = int(x['transact_time'] if kind == 'aggTrades' else x['time'])
        if not START <= when < START + 120000: continue
        trade_id = int(x['agg_trade_id'] if kind == 'aggTrades' else x.get('id', x.get('trade_id')))
        price = Decimal(x['price']); quantity = Decimal(x.get('quantity', x.get('qty')))
        maker = x['is_buyer_maker'].lower()
        if maker not in ('true','false') or price <= 0 or quantity <= 0: raise ValueError('invalid_trade')
        rows.append((when, trade_id, price, quantity, maker))
    rows.sort(key=lambda x: (x[0],x[1]))
    if not rows: raise ValueError('missing_trade_rows')
    return rows

def ohlc(rows):
    return [rows[0][2], max(x[2] for x in rows), min(x[2] for x in rows), rows[-1][2]]

def close(a,b,absolute=1e-8,relative=1e-9):
    return math.isclose(float(a),float(b),abs_tol=absolute,rel_tol=relative)

def main():
    guard()
    frozen = json.loads((FIXED/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'))
    source = FIXED/'逐笔冻结输入'/'2024_candidates.parquet'
    if sha(source.read_bytes()) != frozen['inputs']['2024_candidates.parquet']:
        raise ValueError('candidate_fingerprint')
    all_cand = pd.read_parquet(source)
    cand = all_cand.loc[all_cand.observation_id.eq(OBS)]
    if len(cand) != 1: raise ValueError('candidate_count')
    e = cand.iloc[0]; spec = json.loads(e['long_spec'])
    old = json.loads(OLD.read_text(encoding='utf-8'))
    if old['status'] != 'verified' or len(old['rows']) != 1 or old['rows'][0]['observation_id'] != OBS:
        raise ValueError('prior_record')
    prior = old['rows'][0]; outcome = prior['outcome']
    expected = {x['kind']:x for x in old['archives']}
    archives = []
    body, meta = read_archive('klines', expected['klines']); archives.append(meta); bar = read_minute_bar(body); del body
    body, meta = read_archive('aggTrades', expected['aggTrades']); archives.append(meta); agg = read_window(body,'aggTrades'); del body
    body, meta = read_archive('trades', expected['trades']); archives.append(meta); raw = read_window(body,'trades'); del body
    am = [x for x in agg if x[0] < START+60000]; rm = [x for x in raw if x[0] < START+60000]
    if not am or not rm: raise ValueError('minute_missing')
    official = [bar[k] for k in ('open','high','low','close')]
    av, rv = ohlc(am), ohlc(rm)
    if rv != official or av[0] == official[0] or av[1:] != official[1:]: raise ValueError('ohlc_disagreement')
    raw_base = sum((x[3] for x in rm), Decimal(0))
    raw_quote = sum((x[2]*x[3] for x in rm), Decimal(0))
    if len(rm) != bar['count'] or not close(raw_base,bar['volume'],1e-6) or not close(raw_quote,bar['quote_volume'],1e-5):
        raise ValueError('raw_minute_count_or_volume_disagreement')
    upper, lower = Decimal(str(e['upper'])), Decimal(str(e['lower']))
    def first_cross(rows):
        matches = [x for x in rows if x[0] < START+60000 and (x[2] > upper or x[2] < lower)]
        if not matches: raise ValueError('missing_first_cross')
        return matches[0]
    a, r = first_cross(am), first_cross(rm)
    if (a[0],a[2]) != (r[0],r[2]): raise ValueError('first_cross_disagreement')
    side = 1 if a[2] > upper else -1
    def ref(rows):
        return next(x for x in rows if x[0] >= a[0]+5000)
    ar, rr = ref(agg), ref(raw)
    if (ar[0],ar[2]) != (rr[0],rr[2]): raise ValueError('five_second_reference_disagreement')
    def flow(rows):
        w=[x for x in rows if a[0] < x[0] < a[0]+5000]
        buy=sum((x[2]*x[3] for x in w if x[4]=='false'),Decimal(0))
        sell=sum((x[2]*x[3] for x in w if x[4]=='true'),Decimal(0))
        return len(w),buy,sell
    ac,ab,ass=flow(agg); rc,rb,rs=flow(raw)
    if not close(ab,rb) or not close(ass,rs): raise ValueError('flow_disagreement')
    imb=side*float((ab-ass)/(ab+ass))
    if not (side == 1 and bool(e['long_known_eligible']) and e['market_prior_status']=='allowed'
            and int(e['market_allowed_side'])==side and int(e['trigger_minute'])==int(e['quarter_start'])
            and close(spec['level'],outcome['level']) and close(spec['stop_price'],outcome['stop_price'])
            and (a[0],float(a[2])) == (int(outcome['decision_ts']),float(outcome['signal_close']))
            and (ar[0],float(ar[2])) == (int(outcome['entry_exec_ts']),float(outcome['raw_entry_5s']))
            and ac == outcome['five_count'] and close(ab,outcome['buy_notional']) and close(ass,outcome['sell_notional'])
            and close(imb,outcome['five_imbalance']) and ac>=3 and imb<0.10
            and side*(float(ar[2])-float(spec['level']))>0):
        raise ValueError('candidate_or_rule_disagreement')
    results=json.loads((RETEST/'单次重试跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    selected=[x for x in results if x['year']=='2024' and x['strategy']=='single_retest' and x['leverage']==20]
    if len(selected)!=1: raise ValueError('baseline_row')
    b=selected[0]
    if OBS not in b['unknown_observation_ids'] or b['possible_unknown_events']!=16: raise ValueError('baseline_unknowns')
    n=b['verified_events']; wins=b['verified_wins']; unknown=b['possible_unknown_events']
    output={'all_checks_pass':True,'observation_id':OBS,'archives':archives,
            'original_candidate_sha256':sha(source.read_bytes()),'prior_record_sha256':sha(OLD.read_bytes()),
            'plan_sha256':sha((H/'核验方案.md').read_bytes()),'audit_code_sha256':sha(Path(__file__).read_bytes()),
            'kline_ohlc':[str(x) for x in official],'raw_ohlc':[str(x) for x in rv],
            'aggregate_ohlc':[str(x) for x in av],'kline_count':bar['count'],'raw_count':len(rm),
            'kline_volume':str(bar['volume']),'raw_volume':str(raw_base),
            'kline_quote_volume':str(bar['quote_volume']),'raw_quote_volume':str(raw_quote),
            'first_cross':[a[0],str(a[2])],'five_second_reference':[ar[0],str(ar[2])],
            'aggregate_flow':[str(ab),str(ass)],'raw_flow':[str(rb),str(rs)],
            'raw_window_trade_count':rc,'aggregate_window_trade_count':ac,'imbalance':imb,
            'first_order':'no_order_flow_filter','retry':'ineligible_reference_outside_boundary',
            'prior_fixed11_liquidity_rank':spec['liquidity_rank'],'older_liquidity_rank':outcome['liquidity_rank'],
            'sensitivity_20x':{'verified_events':n,'verified_wins':wins,'old_unknown':unknown,'new_unknown':unknown-1,
                'old_optimistic_win_rate_pct':100*(wins+unknown)/(n+unknown),
                'new_optimistic_win_rate_pct':100*(wins+unknown-1)/(n+unknown-1)},
            'note':'Post-hoc single-event data repair sensitivity; same exchange sources, not an independent venue or new strategy.'}
    (H/'XRP原始成交独立复核与敏感性.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('XRP_SINGLE_EVENT_AUDIT_PASS',json.dumps(output,ensure_ascii=False),flush=True)

if __name__ == '__main__': main()
