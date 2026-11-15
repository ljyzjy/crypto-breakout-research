"""Independently verify recovered-hour accounting and zero-extra-candidate result."""
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
R93 = H.parent / '第九十三轮_原始逐笔抽样交叉核验'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    path = H / '零成交替代口径结果.json'; result = json.loads(path.read_text(encoding='utf-8'))
    q = json.loads((H / '替代排名候选质量.json').read_text(encoding='utf-8'))
    orig = json.loads((R90 / '二零二二候选准备质量.json').read_text(encoding='utf-8'))
    hour = json.loads((H / '零成交小时来源核对.json').read_text(encoding='utf-8'))
    sens = json.loads((R93 / '原始数据分歧敏感性.json').read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'finalize_no_extra.py')
    assert result['candidate_audit_sha256'] == sha(H / '替代排名候选独立核验.json')
    assert result['hour_audit_sha256'] == sha(H / '零成交小时独立核验.json')
    assert result['raw_sensitivity_sha256'] == sha(R93 / '敏感性独立核验.json')
    old = set(orig['unknown_rank_hours_ms']); remaining = set(q['remaining_unknown_hours_ms'])
    assert remaining <= old and len(old) == result['original_unknown_hours']
    assert len(old - remaining) == result['recovered_hours'] and len(remaining) == result['remaining_unknown_hours']
    raw = pd.read_parquet(R90 / '候选数据/固定十一币潜在分钟候选.parquet')
    hours = raw.trigger_minute // 3600000 * 3600000
    assert int(hours.isin(old - remaining).sum()) == result['recovered_raw_potential_events']
    assert int(hours.isin(remaining).sum()) == result['remaining_raw_potential_events']
    extra = pd.read_parquet(H / '替代口径候选/新增潜在触价.parquet')
    assert len(extra) == result['extra_candidates'] == result['extra_trades'] == 0
    assert result['original_invalid_hour_inputs'] == len(hour['hours'])
    assert result['repaired_hour_inputs'] == sum(x['status'] == 'verified_zero_minutes' for x in hour['hours'])
    assert result['unresolved_hour_inputs'] == sum(x['status'] != 'verified_zero_minutes' for x in hour['hours'])
    assert result['baseline_after_raw_sample_sensitivity'] == [x for x in sens['rows'] if x['cohort'] == 'base' and x['exit_slippage_pct'] == .05]
    audit = {'all_checks_pass': True, 'original_rank_hours_checked': len(old), 'recovered_raw_events_checked': result['recovered_raw_potential_events'],
             'remaining_raw_events_checked': result['remaining_raw_potential_events'], 'extra_candidates_checked': len(extra),
             'result_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
             'note': 'Checks only the alternative-hour candidate pipeline; strict minute-feature uncertainties remain.'}
    (H / '替代口径结果独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_FINAL_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
