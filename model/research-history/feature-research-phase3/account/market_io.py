"""Frozen Phase 3 market inputs. Read only; missing rows are never filled.

The four supplemental trade months only support post-pool exits/labels. They
must not be used to alter historical eligibility or fill unavailable features.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT.parents[1]
PHASE2 = OUTPUTS / 'feature-research-phase2'
ORIGINAL = OUTPUTS / 'crypto-spot-kit/short-term-research/minute-intraday-v1'
MANIFEST = ROOT / 'market_manifest.json'
STUDY_END_MS = 1777248000000  # 2026-04-27T00:00:00Z; checked on build
SUPPLEMENTS = {('AAVEUSDT','2025-10'),('RUNEUSDT','2025-04'),
               ('TRUMPUSDT','2025-08'),('UNIUSDT','2026-03')}
TRADE_COLUMNS = ['ts','open','high','low','close','volume','quote_volume']
MARK_COLUMNS = ['ts','open','high','low','close']
FUNDING_COLUMNS = ['ts','funding_interval_hours','last_funding_rate']


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build_manifest():
    """Freeze only input identity and completeness metadata; no outcome reads."""
    p2_path = PHASE2/'data/manifest.json'
    p2_hash = sha256(p2_path)
    if _read(PHASE2/'data/READY.json')['manifest_sha256'] != p2_hash:
        raise ValueError('Phase 2 is not the frozen READY version')
    p2 = _read(p2_path)
    assert p2['study_end_exclusive_ms'] == STUDY_END_MS
    records = [dict(r) for r in p2['records']]
    old_path = ORIGINAL/'data-manifest.json'
    old = _read(old_path)
    existing = {(r['contract'],r['month'],r['kind']) for r in records}
    for r in old['records']:
        if r['kind'] == 'klines' and (r['contract'],r['month']) in SUPPLEMENTS:
            key = (r['contract'],r['month'],r['kind'])
            if key in existing:
                raise ValueError('Supplement overlaps phase 2 source: '+str(key))
            r = dict(r)
            r['path'] = str((ORIGINAL/r['path']).resolve())
            r['source'] = 'original_post_pool_exit_month_supplement'
            r['purpose'] = 'OHLCV settlement and label continuity only; no feature backfill'
            records.append(r)
    supplemental = [r for r in records if r.get('source') == 'original_post_pool_exit_month_supplement']
    assert len(supplemental) == 4
    identities = []
    for r in records:
        path = Path(r['path'])
        actual = sha256(path)
        if actual != r['parquet_sha256']:
            raise ValueError('Input hash differs from source manifest: '+str(path))
        identities.append({'contract':r['contract'],'month':r['month'],'kind':r['kind'],
            'path':str(path.resolve()),'sha256':actual,'rows':r['rows'],
            'first_ts':r['first_ts'],'last_ts':r['last_ts'],
            'source':r.get('source','phase2'),
            'purpose':r.get('purpose','phase2 normalized frozen market input')})
    identities.sort(key=lambda r:(r['contract'],r['month'],r['kind']))
    if len({(r['contract'],r['month'],r['kind']) for r in identities}) != len(identities):
        raise ValueError('Duplicate input key')
    if sha256(p2['daily_pools_path']) != p2['daily_pools_sha256']:
        raise ValueError('Daily pool file changed')
    manifest = {'version':'phase3-unified-market-v1',
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'study_start_ms':p2['study_start_ms'],'study_end_exclusive_ms':STUDY_END_MS,
        'phase2_manifest_path':str(p2_path.resolve()),'phase2_manifest_sha256':p2_hash,
        'original_manifest_path':str(old_path.resolve()),'original_manifest_sha256':sha256(old_path),
        'daily_pools_path':p2['daily_pools_path'],'daily_pools_sha256':p2['daily_pools_sha256'],
        'mapping':p2['mapping'],'quarantine':p2['quarantine'],
        'missing_policy':'Never fill prices/mark/funding/volume; retain zero volume and absent coverage. Future unavailable rows may invalidate labels/account paths but never retrospectively remove opportunities or losses.',
        'settlement_policy':'Raw funding timestamps remain milliseconds. Settlement rates are ex-post accounting, never pre-settlement predictors.',
        'scope_note':'Historical spot top20 eligibility mapped to perpetuals; four supplemental months do not change pools or features.',
        'original_missing':old.get('missing',[]),'records':identities}
    tmp = MANIFEST.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(MANIFEST)
    ready={'manifest_sha256':sha256(MANIFEST),'record_count':len(identities),
           'phase2_records':len(p2['records']),'supplement_count':4,
           'kind_counts':{k:sum(r['kind']==k for r in identities) for k in ('klines','markPriceKlines','fundingRate')},
           'outcomes_computed':False}
    (ROOT/'MARKET_READY.json').write_text(json.dumps(ready,indent=2),encoding='utf-8')
    return ready


@lru_cache(maxsize=1)
def get_manifest():
    if not MANIFEST.exists():
        raise RuntimeError('Run market_io.py to freeze inputs before reading')
    ready = _read(ROOT/'MARKET_READY.json')
    if sha256(MANIFEST) != ready['manifest_sha256']:
        raise ValueError('Frozen market manifest changed')
    result = _read(MANIFEST)
    if sha256(result['phase2_manifest_path']) != result['phase2_manifest_sha256']:
        raise ValueError('Phase 2 manifest changed')
    return result


@lru_cache(maxsize=2048)
def _verify_input(path, expected):
    if sha256(path) != expected:
        raise ValueError('Frozen market input changed: '+path)
    return True


def records_for(contract, kind='klines', start_ms=None, end_ms=None):
    manifest = get_manifest()
    end = min(int(end_ms), STUDY_END_MS) if end_ms is not None else STUDY_END_MS
    return [r for r in manifest['records'] if r['contract']==contract and r['kind']==kind
        and r['first_ts']<end and (start_ms is None or r['last_ts']>=int(start_ms))]


def _load(contract, kind, columns, start_ms=None, end_ms=None):
    end = min(int(end_ms), STUDY_END_MS) if end_ms is not None else STUDY_END_MS
    chunks=[]
    for r in records_for(contract,kind,start_ms,end):
        _verify_input(r['path'],r['sha256'])
        d=pd.read_parquet(r['path'],columns=columns)
        mask=d.ts.lt(end)
        if start_ms is not None:
            mask &= d.ts.ge(int(start_ms))
        chunks.append(d.loc[mask])
    if not chunks:
        return pd.DataFrame({c:pd.Series(dtype='int64' if c=='ts' else 'float64') for c in columns})
    result=pd.concat(chunks,ignore_index=True).sort_values('ts').reset_index(drop=True)
    if result.ts.duplicated().any():
        raise ValueError('Duplicate timestamp '+contract+' '+kind)
    if result.ts.notna().all():
        result['ts']=result.ts.astype('int64')
    return result


def load_minutes(contract, start_ms=None, end_ms=None):
    return _load(contract,'klines',TRADE_COLUMNS,start_ms,end_ms)


def load_mark(contract, start_ms=None, end_ms=None):
    return _load(contract,'markPriceKlines',MARK_COLUMNS,start_ms,end_ms)


def load_funding(contract, start_ms=None, end_ms=None):
    return _load(contract,'fundingRate',FUNDING_COLUMNS,start_ms,end_ms)


def load_mapping():
    return get_manifest()['mapping'].copy()


def load_daily_pools():
    m=get_manifest()
    _verify_input(m['daily_pools_path'],m['daily_pools_sha256'])
    return _read(m['daily_pools_path'])


def load_quarantine():
    return get_manifest()['quarantine'].copy()


if __name__=='__main__':
    print(json.dumps(build_manifest(),ensure_ascii=False))
