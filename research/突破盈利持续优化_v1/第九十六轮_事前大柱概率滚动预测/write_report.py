"""Document the pre-entry big-candle model and fixed payoff gate."""
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, digits=2):
    return '—' if v is None else f'{v:.{digits}f}'


def main():
    result = json.loads((H / '大柱概率滚动结果.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '大柱概率模型独立核验.json').read_text(encoding='utf-8'))
    labels = json.loads((H / '事后大柱标签独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '大柱概率滚动结果.json')
    assert labels['all_checks_pass'] and labels['label_sha256'] == sha(H / '事后大柱训练标签.parquet')
    scores = pd.read_csv(H / '评分明细.csv')
    periods = {'2023':'2023', '2024':'2024 上半年', '2026':'2026 年 5—7 月', '2026_aug_oct':'2026 年 8—10 月'}
    lines = ['# 事前大柱概率的滚动预测', '',
             '以历史已完成柱是否形成大顺向实体作为训练标签，测试时只输入入场前的八项特征；训练期大柱与其他柱各自的扣费后平均收益，用来计算预期净收益门槛。下表为 20×，10× 完整结果也在明细中。', '',
             '| 评分时段 | 训练笔数／大柱 | 评分笔数 | 训练期盈亏平衡大柱概率 | 最高预测大柱概率 | 模型保留交易 | 原基准交易／净盈利 | 已列候选未知 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for period in ('2023','2024','2026','2026_aug_oct'):
        r = next(x for x in result['rows'] if x['test_period'] == period and x['leverage'] == 20)
        g = scores[(scores.test_period == period) & scores.leverage.eq(20) & scores.status.eq('scored')]
        maximum = float(g.probability.max()) if len(g) else None
        threshold = r['break_even_big_probability']
        lines.append(f"| {periods[period]} | {r['train_rows']}／{r['train_big']} | {r['scored']} | {fmt(100*threshold if threshold is not None else None)}% | {fmt(100*maximum if maximum is not None else None)}% | {r['model']['known_trades']} | {r['baseline']['known_trades']}／{r['baseline']['net_wins']} | {r['model']['unknown_candidates']} |")
    selected = sum(x['model']['known_trades'] for x in result['rows'])
    lines += ['', f"10× 和 20× 共 {len(result['rows'])} 个测试组，模型合计保留 {selected} 笔。没有交易时，净胜率与收益不可计算，不能称为实现盈利。", '',
              '以 20× 的 2022 年训练集为例，20 笔事后大柱平均名义净收益约 +0.5516%，94 笔其他柱平均约 -0.4886%；在将这两个类内均值用于后续交易的假设下，需要预测大柱概率超过约 46.97% 才有正的估计净收益。该门槛不是实际盈亏保证，概率也尚未证明校准。', '',
              f"独立核验了 {labels['labels_checked']} 个事后标签、重取 {labels['late_daily_archives_redownloaded']} 份官方日档样本，并用 Newton 法重拟合 {audit['model_groups_checked']} 组模型、核对 {audit['scored_paths_checked']} 条评分路径。每个训练标签都在评分时段之前完成，测试柱收盘只参与事后核验。", '',
              '此前已查看这些历史时段和大柱分组，本轮是在反复探索后提出的时间顺序研究，不能称为独立盲样。2022 年原口径的排名未知小时、原始与聚合成交分歧、持仓量实时发布时间及真实市价成交均未完全解决；不包含完整账户或真实强平验证。', '',
              '[冻结方案](冻结研究方案.md) · [逐笔标签](事后大柱训练标签.parquet) · [全部评分](评分明细.csv) · [模型结果](大柱概率滚动结果.json) · [独立核验](大柱概率模型独立核验.json)']
    (H / '事前大柱概率滚动结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT96_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
