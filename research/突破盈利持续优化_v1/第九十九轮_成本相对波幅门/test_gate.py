"""Verify the fixed 0.4% stop-distance boundary for long and short signals."""
import json
from pathlib import Path
import run_wallet as wallet

H=Path(__file__).resolve().parent


def main():
    rows=[{'observation_id':'long_at','reference':'100','stop':'99.6','side':1},
          {'observation_id':'long_below','reference':'100','stop':'99.6001','side':1},
          {'observation_id':'short_at','reference':'100','stop':'100.4','side':-1},
          {'observation_id':'short_below','reference':'100','stop':'100.3999','side':-1}]
    wallet.baseline.load_records=lambda:rows
    got={r['observation_id'] for r in wallet.load_records()};assert got=={'long_at','short_at'}
    out={'all_checks_pass':True,'cases_checked':len(rows),'wallet_code_sha256':wallet.bulk.sha(H/'run_wallet.py'),
         'test_code_sha256':wallet.bulk.sha(Path(__file__)),'note':'Signal-time boundary only; no execution or profit guarantee.'}
    (H/'成本门边界合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT99_BOUNDARY_PASS',len(rows),flush=True)


if __name__=='__main__':main()
