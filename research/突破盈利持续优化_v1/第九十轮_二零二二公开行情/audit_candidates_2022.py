"""Independently audit 2022 ranks and candidate gates before tick replay."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import psutil

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
R43 = H.parent / '第四十三轮_旧十一币2023年复核'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def patched(path, replacements, output, candidate_dir):
    source = path.read_text(encoding='utf-8')
    for a, b in replacements:
        assert source.count(a) == 1, a
        source = source.replace(a, b)
    env = {'__name__': 'independent_2022_audit', '__file__': str(path), 'AUDIT_FILE': output}
    exec(compile(source, str(path), 'exec'), env)
    env['H'] = candidate_dir
    return env


def main():
    root = Path(json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))['data_root'])
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or shutil.disk_usage(root).free < 5_000_000_000:
        raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available < 850 * 1024 ** 2:
        raise RuntimeError('memory_headroom')
    quality = json.loads((H / '二零二二候选准备质量.json').read_text(encoding='utf-8'))
    assert quality['parity_and_causality']['all_checks_pass']
    candidates = H / '候选数据'
    for name, digest in quality['outputs_sha256'].items():
        assert sha(candidates / name) == digest, name
    supplement = json.loads((H / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    final = root / 'normalized_final_audit_links'
    final.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in supplement['selected_sources']:
        src = Path(item['path'])
        assert sha(src) == item['sha256']
        dst = final / (item['symbol'] + '_klines.parquet')
        if not dst.exists():
            os.link(src, dst)
        assert sha(dst) == item['sha256']
        manifest.append({'symbol': item['symbol'], 'path': str(dst), 'sha256': sha(dst),
                         'source': str(src), 'kind': 'read_only_hardlink'})
    rank_source = R43 / 'audit_old11_ranks.py'
    rank = patched(rank_source, [("(H/'2023日小时排名独立核验.json').write_text", 'AUDIT_FILE.write_text')],
                   H / '二零二二日小时排名独立核验.json', candidates)
    rank['NORM'] = final
    rank['main']()
    event_source = R43 / 'audit_old11_candidates.py'
    event = patched(event_source,
        [("H/'2023双币过滤潜在触价.parquet'", "H/'固定十一币双币过滤潜在触价.parquet'"),
         ("(H/'2023候选特征独立核验.json').write_text", 'AUDIT_FILE.write_text')],
        H / '二零二二候选特征独立核验.json', candidates)
    event['main']()
    for name, digest in quality['outputs_sha256'].items():
        assert sha(candidates / name) == digest, name
    a, b = H / '二零二二日小时排名独立核验.json', H / '二零二二候选特征独立核验.json'
    assert json.loads(a.read_text(encoding='utf-8'))['all_checks_pass']
    assert json.loads(b.read_text(encoding='utf-8'))['all_checks_pass']
    result = {'all_checks_pass': True, 'inputs_unchanged': True,
              'candidate_quality_sha256': sha(H / '二零二二候选准备质量.json'),
              'rank_audit_sha256': sha(a), 'event_audit_sha256': sha(b),
              'rank_source_sha256': sha(rank_source), 'event_source_sha256': sha(event_source),
              'wrapper_sha256': sha(Path(__file__)), 'sources': manifest,
              'note': 'Sampled independent rank/source checks; unknown rank hours remain unknown.'}
    (H / '二零二二候选独立核验总表.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_INDEPENDENT_AUDIT', json.dumps({k: v for k, v in result.items() if k != 'sources'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
