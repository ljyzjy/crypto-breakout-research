"""Summarize the limited raw-vs-aggregate check and conservative sensitivity."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, n=4):
    return '—' if v is None else f'{v:.{n}f}'


def main():
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '原始逐笔独立核验.json').read_text(encoding='utf-8'))
    sens = json.loads((H / '原始数据分歧敏感性.json').read_text(encoding='utf-8'))
    check = json.loads((H / '敏感性独立核验.json').read_text(encoding='utf-8'))
    timing = json.loads((H / '前五分钟分歧敏感性.json').read_text(encoding='utf-8'))
    timing_check = json.loads((H / '前五分钟敏感性独立核验.json').read_text(encoding='utf-8'))
    wallets = json.loads((H / '共享钱包情景汇总.json').read_text(encoding='utf-8'))
    wallet_check = json.loads((H / '共享钱包独立核验.json').read_text(encoding='utf-8'))
    breakdown = json.loads((H / '突破柱分解敏感性.json').read_text(encoding='utf-8'))
    breakdown_check = json.loads((H / '突破柱敏感性独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['source_sha256'] == sha(H / '原始聚合逐笔样本对照.json')
    assert check['all_checks_pass'] and check['result_sha256'] == sha(H / '原始数据分歧敏感性.json')
    assert timing_check['all_checks_pass'] and timing_check['result_sha256'] == sha(H / '前五分钟分歧敏感性.json')
    assert wallet_check['all_checks_pass'] and wallet_check['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    assert breakdown_check['all_checks_pass'] and breakdown_check['result_sha256'] == sha(H / '突破柱分解敏感性.json')
    lines = ['# 2022 年原始成交与聚合成交抽样对照', '',
             '按独立逐笔样本的预定顺序，对最多三个候选核对官方原始成交和聚合成交的首次突破、严格首秒买卖成交额、一秒参考价及适用时的延迟入场参考价。', '',
             '| 样本 | 聚合方案状态 | 来源对照 | 分项结果 |', '|---|---|---|---|']
    labels = {'agree': '一致', 'disagree': '存在分歧', 'unknown': '未完成／未知'}
    for r in raw['samples']:
        checks = ', '.join(f"{k}={'一致' if v else '分歧'}" for k, v in r.get('checks', {}).items()) or r.get('error', '未知')
        identifier = r['observation_id'].replace('|', '\\|')
        lines.append(f"| {identifier} | {r['signal_status']} | {labels[r['status']]} | {checks} |")
    lines += ['', '将分歧或未完成的样本保守改列为未知，并仅从单位机会汇总移除，得到：', '',
              '| 20× 基础方案 | 聚合口径交易／未知 | 敏感性交易／未知 | 净盈利 | 平均名义净收益 |',
              '|---|---:|---:|---:|---:|']
    for holding, name in [('original', '原柱末'), ('extended', '延长一柱')]:
        r = next(x for x in sens['rows'] if x['holding_rule'] == holding and x['leverage'] == 20 and x['cohort'] == 'base' and x['exit_slippage_pct'] == .05)
        lines.append(f"| {name} | {r['baseline_trades']}／{r['baseline_unknown']} | {r['trades']}／{r['sensitivity_unknown']} | {r['net_wins']} | {fmt(r['mean_net_pct_notional'])}% |")
    e = next(x for x in timing['rows'] if x['period'] == '2022' and x['holding_rule'] == 'original' and x['leverage'] == 20
             and x['cohort'] == 'base' and x['timing'] == 'early' and x['exit_slippage_pct'] == .05)
    lines += ['', f"同样排除分歧样本后，20× 前五分钟方案为 {e['known_trades']} 笔、{e['net_wins']} 笔净盈利，"
              f"净胜率 {fmt(e['net_win_rate_pct'],2)}%，平均名义净收益 {fmt(e['mean_net_pct_notional'])}%；已列候选保守未知 {e['unknown_candidates_conservative']} 个。", '',
              '| 20× 原柱末已知路径钱包 | 模拟成交 | 期末钱包 | 净收益率 | 已实现钱包余额回撤 |',
              '|---|---:|---:|---:|---:|']
    for period, name in [('original_all', '不限触发时间'), ('original_early', '前五分钟')]:
        w = next(x for x in wallets['rows'] if x['period'] == period and x['cohort'] == 'base' and x['leverage'] == 20 and not x['reverse_ties'])
        lines.append(f"| {name} | {w['simulated_trades']} | {fmt(w['final_wallet'],2)} U | {fmt(w['net_return_pct'],2)}% | {fmt(w['realized_wallet_drawdown_pct'],2)}% |")
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        ledger = [x for x in csv.DictReader(f) if x['cohort'] == 'base' and x['period'] == 'original_all'
                  and x['leverage'] == '20' and x['reverse_ties'] == 'False' and x['status'] == 'closed']
    breaches = [x for x in ledger if Decimal(x['net_pnl']) < -Decimal(x['reference_wallet']) * Decimal('.005')]
    worst = min((Decimal(x['net_pnl']) / Decimal(x['reference_wallet']) * 100 for x in ledger), default=Decimal(0))
    lines += ['', f"不限触发时间的已知路径中，{len(breaches)}/{len(ledger)} 笔最终亏损超过信号时钱包余额的 0.5%，"
              f"最差为 {float(worst):.4f}%。0.5% 是计划风险，不能保证最终亏损上限。"]
    large = next(x for x in breakdown['rows'] if x['holding_rule'] == 'original' and x['leverage'] == 20 and x['group'] == 'large_aligned')
    other = next(x for x in breakdown['rows'] if x['holding_rule'] == 'original' and x['leverage'] == 20 and x['group'] == 'other')
    lines += ['', f"剔除分歧路径后，事后形成大顺向实体柱的 {large['trades_with_known_bar']} 笔平均名义净收益 {fmt(large['mean_actual_net_pct'])}%；"
              f"其余已知柱的 {other['trades_with_known_bar']} 笔平均 {fmt(other['mean_actual_net_pct'])}%。这是用收盘后的柱形作描述，不能用于事前挑选交易。"]
    lines += ['', f"独立解析并复核 {audit['samples_checked']} 个样本，另有 {audit['unknown_samples_skipped']} 个未知；敏感性 {check['groups_checked']} 个汇总组独立复算。无论样本是否一致，均无法据此推断未抽样候选的原始与聚合时间完全一致。", '',
              '聚合笔数与原始成交笔数的统计口径不同，本研究没有以原始笔数替代三笔聚合成交门槛。此检查也不验证同毫秒真实跨流顺序、盘口、实际市价成交、账户回撤或强平。2022 年原口径另有 240 个排名未知小时；零成交小时的替代核验恢复了其中 196 个，余 44 个仍未知，恢复部分无新增候选。[替代口径核验](../第九十四轮_零成交分钟排名补充/零成交小时替代口径结果.md) 历史币池以后来固定的 11 币为准。钱包跳过未知候选且不含浮动盈亏，余额回撤不能当作真实账户最大回撤。', '',
              '[逐项对照](原始聚合逐笔样本对照.json) · [独立核验](原始逐笔独立核验.json) · [全部敏感性](原始数据分歧敏感性.json) · [前五分钟敏感性](前五分钟分歧敏感性.json) · [钱包核验](共享钱包独立核验.json)']
    (H / '原始聚合逐笔抽样结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT93_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
