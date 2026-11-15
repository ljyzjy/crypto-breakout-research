"""Close the alternative data-semantics study when there are no added candidates."""
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
    q = json.loads((H / '替代排名候选质量.json').read_text(encoding='utf-8'))
    a = json.loads((H / '替代排名候选独立核验.json').read_text(encoding='utf-8'))
    hour = json.loads((H / '零成交小时来源核对.json').read_text(encoding='utf-8'))
    ha = json.loads((H / '零成交小时独立核验.json').read_text(encoding='utf-8'))
    progress = json.loads((H / '新增候选逐笔回放进度.json').read_text(encoding='utf-8'))
    batch = json.loads((H / '一秒回放批次/动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    sens = json.loads((R93 / '原始数据分歧敏感性.json').read_text(encoding='utf-8'))
    sa = json.loads((R93 / '敏感性独立核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['candidate_quality_sha256'] == sha(H / '替代排名候选质量.json')
    assert ha['all_checks_pass'] and ha['source_sha256'] == sha(H / '零成交小时来源核对.json')
    assert sa['all_checks_pass'] and sa['result_sha256'] == sha(R93 / '原始数据分歧敏感性.json')
    assert q['extra_candidates'] == progress['total_candidates'] == batch['candidate_events'] == 0
    assert progress['total_groups'] == progress['completed_groups'] == 0 and batch['variant_paths'] == 0
    raw = pd.read_parquet(R90 / '候选数据/固定十一币潜在分钟候选.parquet')
    remaining = int((raw.trigger_minute // 3600000 * 3600000).isin(q['remaining_unknown_hours_ms']).sum())
    assert remaining + q['recovered_raw_potential_events'] == 182
    rows = [x for x in sens['rows'] if x['cohort'] == 'base' and x['exit_slippage_pct'] == .05]
    result = {'process_complete': True, 'original_unknown_hours': q['original_unknown_rank_hours'],
              'recovered_hours': q['recovered_rank_hours'], 'remaining_unknown_hours': q['remaining_unknown_rank_hours'],
              'original_invalid_hour_inputs': sum(hour['hour_statuses'].values()),
              'repaired_hour_inputs': hour['hour_statuses'].get('verified_zero_minutes', 0),
              'unresolved_hour_inputs': sum(v for k, v in hour['hour_statuses'].items() if k != 'verified_zero_minutes'),
              'recovered_raw_potential_events': q['recovered_raw_potential_events'],
              'remaining_raw_potential_events': remaining, 'extra_candidates': 0, 'extra_trades': 0,
              'baseline_after_raw_sample_sensitivity': rows, 'candidate_audit_sha256': sha(H / '替代排名候选独立核验.json'),
              'hour_audit_sha256': sha(H / '零成交小时独立核验.json'), 'raw_sensitivity_sha256': sha(R93 / '敏感性独立核验.json'),
              'code_sha256': sha(Path(__file__)),
              'note': 'Alternative verified zero-volume-hour semantics; strict minute-feature gaps, unknown rank hours and other source uncertainty remain.'}
    (H / '零成交替代口径结果.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# 零成交小时替代口径结果', '',
             f"原来使排名无法判断的 {q['original_unknown_rank_hours']} 个小时中，替代口径恢复 {q['recovered_rank_hours']} 个，另 {q['remaining_unknown_rank_hours']} 个仍未知。"
             f"37 个原始无效小时输入中，{result['repaired_hour_inputs']} 个与官方小时线一致，{result['unresolved_hour_inputs']} 个存在分歧，继续保留未知。", '',
             f"恢复小时内有 {q['recovered_raw_potential_events']} 条初步触价记录，经既定小时排名与 BTC／ETH 市场条件核验，"
             f"新增可逐笔回放候选 {q['extra_candidates']} 条；剩余未知小时内有 {remaining} 条初步触价记录，不能当作无交易。", '',
             '原模型冻结结果不变。由于本替代口径没有新增候选，现有已知交易及其聚合／原始分歧敏感性收益不变；此前已知小时的排名及名次完全一致，重算分数最大的浮点绝对差小于 1e-13。', '',
             '本研究仅允许已记录、价格自洽且零成交的分钟进入小时计算，并要求官方小时线对应字段一致；它不能证明交易所当时服务状态、原始成交完整或实盘可执行。原分钟特征仍使用严格有效性规则，相关时段潜在机会不能声称完整。该历史样本以后来固定的 11 币为准，仍有幸存者偏差。', '',
             '[替代口径与冻结规则](冻结研究方案.md) · [小时来源核验](零成交小时独立核验.json) · [全部候选门独立核验](替代排名候选独立核验.json) · [原始成交分歧敏感性](../第九十三轮_原始逐笔抽样交叉核验/原始聚合逐笔抽样结果.md)']
    (H / '零成交小时替代口径结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT94_FINISH', json.dumps({k: result[k] for k in ('recovered_hours', 'remaining_unknown_hours', 'recovered_raw_potential_events', 'remaining_raw_potential_events', 'extra_candidates')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
