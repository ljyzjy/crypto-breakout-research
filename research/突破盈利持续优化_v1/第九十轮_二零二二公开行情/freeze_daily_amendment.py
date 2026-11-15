import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    target = H / '日档补源规则冻结.json'
    assert not target.exists()
    q = json.loads((H / '二零二二分钟数据质量.json').read_text(encoding='utf-8'))
    assert q['all_symbols_verified'] and q['total_missing_minutes'] == 28800
    out = {'original_freeze_sha256': sha(H / '冻结时点.json'), 'original_quality_sha256': sha(H / '二零二二分钟数据质量.json'),
           'original_archive_manifest_sha256': sha(H / '月线分钟档案来源.json'),
           'amendment_sha256': sha(H / '日档补源规则.md'), 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'Source repair fixed after observing missing minutes and before candidate or PnL calculation.'}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_DAILY_AMENDMENT_FREEZE', sha(target), flush=True)


if __name__ == '__main__':
    main()
