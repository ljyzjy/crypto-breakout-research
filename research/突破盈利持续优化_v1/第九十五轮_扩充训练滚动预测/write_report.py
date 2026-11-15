"""Present time-ordered model results and the no-trade outcome transparently."""
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, digits=3):
    return '—' if v is None else f'{v:.{digits}f}'


def main():
    result = json.loads((H / '扩充训练滚动结果.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '扩充滚动模型独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '扩充训练滚动结果.json')
    scores = pd.read_csv(H / '滚动评分明细.csv')
    labels = {'2023': '2023', '2024': '2024 上半年', '2026': '2026 年 5—7 月', '2026_aug_oct': '2026 年 8—10 月'}
    lines = ['# 扩充 2022 年训练后的事前滚动模型', '',
             '复用先前固定的八特征逻辑回归，只用测试期之前已经退出的交易训练；入场、退出、手续费、滑点、资金费和风险代理均沿用原规则。下表为 20× 单位机会，10× 结果也保留在明细中。', '',
             '| 评分时段 | 训练笔数／净盈利 | 评分笔数 | 训练盈亏平衡概率 | 最高预测胜率 | 模型保留交易 | 原基准交易／净盈利 | 未知候选 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for period in ('2023', '2024', '2026', '2026_aug_oct'):
        r = next(x for x in result['rows'] if x['test_period'] == period and x['leverage'] == 20)
        g = scores[(scores.test_period == period) & scores.leverage.eq(20) & scores.status.eq('scored')]
        maxp = None if g.empty else float(g.probability.max())
        lines.append(f"| {labels[period]} | {r['train_rows']}／{r['train_wins']} | {r['scored']} | {fmt(r['training_breakeven_probability']*100,2)}% | {fmt(maxp*100 if maxp is not None else None,2)}% | {r['model']['known_trades']} | {r['baseline']['known_trades']}／{r['baseline']['net_wins']} | {r['model']['unknown_candidates']} |")
    selected = sum(x['model']['known_trades'] for x in result['rows'])
    lines += ['', f"全部 {len(result['rows'])} 个杠杆／测试段组中，模型合计保留 {selected} 笔；没有交易时胜率和收益均不可计算，不能称为盈利方案。", '',
              f"独立核验以 Newton 法重拟合 {audit['model_groups_checked']} 个模型，重算 {audit['scored_paths_checked']} 条评分路径并检查先后时序。2022 年训练数据排除了已发现原始与聚合成交分歧的样本；其余未抽样数据仍有类似不确定性。", '',
              '盈亏平衡门槛由训练期平均盈利和平均非正收益估算，假设两类盈亏幅度可用于后续交易，模型概率也未证明校准。较少测试交易上的 AUC 仅是描述性指标，不证明未来可交易优势。持仓量使用至少 15 分钟滞后，历史实际发布时间未得到证明。', '',
              '本方案是在各历史时段已被研究、且已查看 2022 年整体结果后固定的；时间顺序验证不能代替独立未来样本。原始未知候选、2022 年原口径 240 个排名未知小时及替代口径剩余 44 个未知小时均未被该模型解决；无共享账户或真实执行验证。', '',
              '[冻结方案](冻结研究方案.md) · [完整评分](滚动评分明细.csv) · [模型参数](滚动模型参数.json) · [所有时段结果](扩充训练滚动结果.json) · [独立核验](扩充滚动模型独立核验.json)']
    (H / '扩充训练滚动预测结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT95_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
