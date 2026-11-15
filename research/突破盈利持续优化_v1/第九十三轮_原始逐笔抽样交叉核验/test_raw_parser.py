"""Check independent parsers and aggregation-aware synthetic second windows."""
import hashlib
import json
from pathlib import Path
import zipfile

import audit_raw_samples as independent
import compare_raw_aggregate as compare

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    compare.runner.guard(start=True)
    root = compare.runner.ROOT / 'synthetic_raw_aggregate'
    root.mkdir(parents=True, exist_ok=True)
    agg = ('123,1.25,2,10,11,1640995200023,false\n'
           '124,1.26,3,12,13,1640995200123,false\n'
           '125,1.27,1,14,14,1640995201023,true\n'
           '126,1.28,1,15,15,1640995202023,false\n')
    raw = ('10,1.25,1,1.25,1640995200023,false\n'
           '11,1.25,1,1.25,1640995200023,false\n'
           '12,1.26,1,1.26,1640995200123,false\n'
           '13,1.26,2,2.52,1640995200123,false\n'
           '14,1.27,1,1.27,1640995201023,true\n'
           '15,1.28,1,1.28,1640995202023,false\n')
    for kind, content in [('aggTrades', agg), ('trades', raw)]:
        path = root / (kind + '_synthetic.zip')
        if not path.exists():
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z: z.writestr('sample.csv', content)
        a = compare.read_window(path, kind, 1640995200000, 1640995205000)
        b = independent.independent_window(path, kind, 1640995200000, 1640995205000)
        assert a == b
        if kind == 'aggTrades': aa = a
        else: rr = a
    start = 1640995200023
    assert compare.first_cross(aa, 1640995200000, compare.D('1.2'), compare.D('1')) == compare.first_cross(rr, 1640995200000, compare.D('1.2'), compare.D('1'))
    a, b = compare.amounts(aa, start), compare.amounts(rr, start)
    assert compare.D(a['buy']) == compare.D(b['buy']) and compare.D(a['sell']) == compare.D(b['sell'])
    assert a['records'] != b['records']
    assert compare.first_after(aa, start + 1000) == compare.first_after(rr, start + 1000)
    assert compare.first_after(aa, start + 2000) == compare.first_after(rr, start + 2000)
    out = {'all_checks_pass': True, 'raw_and_aggregate_records': [len(rr), len(aa)],
           'independent_parsers_agree': True, 'aggregate_count_differs_but_notional_matches': True,
           'code_sha256': sha(Path(__file__)), 'raw_parser_sha256': sha(H / 'compare_raw_aggregate.py'),
           'independent_parser_sha256': sha(H / 'audit_raw_samples.py')}
    (H / '无表头合成核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_SYNTHETIC_PASS', json.dumps(out), flush=True)


if __name__ == '__main__':
    main()
