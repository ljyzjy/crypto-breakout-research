"""Read-only access to the versioned phase-2 minute input. No fills or future labels."""
from pathlib import Path
import json,hashlib
import pandas as pd

ROOT=Path(__file__).resolve().parent
COLUMNS=['ts','open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume']

def _manifest():
    ready_path=ROOT/'data'/'READY.json'
    if not ready_path.exists():raise RuntimeError('Phase2 data is not READY; partial inputs cannot be used')
    ready=json.loads(ready_path.read_text(encoding='utf-8'))
    raw=(ROOT/'data'/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ready['manifest_sha256']:
        raise RuntimeError('Phase2 manifest does not match frozen READY version')
    return json.loads(raw.decode('utf-8'))

def load_mapping():return _manifest()['mapping'].copy()
def list_contracts():return sorted({r['contract'] for r in _manifest()['records'] if r['kind']=='klines'})
def load_daily_pools():return json.loads(Path(_manifest()['daily_pools_path']).read_text(encoding='utf-8'))
def load_quarantine():return _manifest()['quarantine'].copy()

def load_minutes(contract,start_ms=None,end_ms=None):
    """Return existing rows [start_ms,end_ms), UTC open milliseconds, bounded by study end."""
    manifest=_manifest()
    end_ms=min(int(end_ms),manifest['study_end_exclusive_ms']) if end_ms is not None else manifest['study_end_exclusive_ms']
    chunks=[]
    for r in manifest['records']:
        if r['kind']!='klines' or r['contract']!=contract:continue
        if start_ms is not None and r['last_ts']<start_ms:continue
        if r['first_ts']>=end_ms:continue
        d=pd.read_parquet(r['path'],columns=COLUMNS)
        mask=d.ts.lt(end_ms)
        if start_ms is not None:mask &= d.ts.ge(int(start_ms))
        chunks.append(d.loc[mask])
    if not chunks:return pd.DataFrame({c:pd.Series(dtype='int64' if c in ('ts','trade_count') else 'float64') for c in COLUMNS})
    d=pd.concat(chunks,ignore_index=True).sort_values('ts').reset_index(drop=True)
    if d.ts.duplicated().any():raise ValueError('Duplicate minute key: '+contract)
    return d
