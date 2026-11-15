"""Report a descriptive ex-post decomposition of completed breakout candles."""
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, n=4):
    return '—' if v is None else f'{v:.{n}f}'


def main():
    result = json.loads((H / '突破柱收益分解.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '突破柱分解独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '突破柱收益分解.json')
    labels = {'all': '全部已知柱', 'large_aligned': '事后大顺向实体柱', 'other': '其余已知柱'}
    lines = ['# 已成交路径中的突破柱收益分解', '',
             '按交易方向计，柱整体变化分为“开柱到入场参考价”和“入场参考价到柱收盘价”。实际持有价差是从入场参考价到模拟退出参考价；退出可能早于或晚于柱末。所有百分比均以模拟入场成交价为分母。', '',
             '| 20× 持有／事后组别 | 已知柱交易 | 整柱变化 | 入场前变化 | 入场后至柱末变化 | 实际持有原始价差 | 扣成本实际净收益 | 柱特征未知 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for holding, label in [('original', '原柱末'), ('extended', '延长一柱')]:
      for group in ('all', 'large_aligned', 'other'):
        r = next(x for x in result['rows'] if x['holding_rule'] == holding and x['leverage'] == 20 and x['group'] == group)
        lines.append(f"| {label}／{labels[group]} | {r['trades_with_known_bar']} | {fmt(r['mean_entire_pct'])}% | {fmt(r['mean_before_entry_pct'])}% | {fmt(r['mean_after_entry_to_close_pct'])}% | {fmt(r['mean_actual_raw_held_pct'])}% | {fmt(r['mean_actual_net_pct'])}% | {r['unknown_bar_count']} |")
    lines += ['', '大顺向实体柱定义为：最终柱收盘相对开盘、沿交易方向的变化达到事前 ATR 的一倍。柱收盘是事后结果，这个标签只用于分析，不能用它作为当时的入场条件。分母是已有模拟成交且柱数据可判定的交易，并非全市场所有大柱，因此表中数量不是大柱捕获率。', '',
              f"独立复核 {audit['path_rows_checked']} 条路径和 {audit['summary_groups_checked']} 个分组。2022 年币池以后来固定的 11 币为准，排名未知小时和未知交易仍未纳入；价格与费用是公开历史数据上的模拟代理，不表示实际成交。", '',
              '上表沿用聚合成交原口径。后续抽查发现原始与聚合来源存在分歧；剔除相关样本后的大柱分解见[来源分歧敏感性](../第九十三轮_原始逐笔抽样交叉核验/突破柱分解敏感性.json)。', '',
              '[逐笔分解](突破柱逐笔分解.csv) · [全部汇总](突破柱收益分解.json) · [独立核验](突破柱分解独立核验.json) · [冻结口径](冻结研究方案.md)']
    (H / '突破柱收益分解结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT92_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
