"""Write a results-bounded report after all required audits have passed."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, digits=3):
    return '—' if v is None else f'{v:.{digits}f}'


def main():
    summary = json.loads((H / '二零二二一秒回测汇总.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '二零二二汇总独立核验.json').read_text(encoding='utf-8'))
    wallet = json.loads((H / '共享钱包情景汇总.json').read_text(encoding='utf-8'))
    wallet_audit = json.loads((H / '共享钱包独立核验.json').read_text(encoding='utf-8'))
    risk = json.loads((H / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    tape = json.loads((H / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8'))
    oi = json.loads((H / '持仓量逐点独立核验.json').read_text(encoding='utf-8'))
    diagnosis = json.loads((H / '未知排名小时来源诊断.json').read_text(encoding='utf-8'))
    progress = json.loads((H / '一秒逐笔回放进度.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256'] == sha(H / '二零二二一秒回测汇总.json')
    assert wallet_audit['all_checks_pass'] and wallet_audit['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    assert all(x['all_checks_pass'] for x in (risk, tape, oi, diagnosis))
    labels = {'base': '基础', 'distance': '首秒追价距离', 'oi': '双币持仓量', 'oi_distance': '距离＋持仓量'}
    holds = {'original': '原柱末', 'extended': '延长一柱'}
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        wallet_detail = list(csv.DictReader(f))
    lines = ['# 2022 年一秒观察、市价代理回测', '',
             f"候选覆盖：可判断排名的 310 个候选中，逐笔任务完成 {progress['completed_groups']}/{progress['total_groups']} 批次；"
             f"另有 {diagnosis['unknown_rank_hours']} 个小时因历史零成交分钟无法按既定规则排名，包含 "
             f"{diagnosis['raw_potential_events_during_unknown_rank_hours']} 条初步触价记录，均不能判为无机会。", '',
             '| 20× 持有规则／过滤 | 已核验交易／净盈利 | 净胜率 | 平均名义净收益 | 利润因子 | 活跃 UTC 日 | 已列候选未知 | 退出滑点 0.075% 的平均净收益 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for holding in ('original', 'extended'):
        for cohort in labels:
            def get(slip):
                return next(x for x in summary['rows'] if x['holding_rule'] == holding and x['leverage'] == 20 and x['cohort'] == cohort and x['exit_slippage_pct'] == slip)
            r, stress = get(.05), get(.075)
            lines.append(f"| {holds[holding]}／{labels[cohort]} | {r['trades']}／{r['net_wins']} | {fmt(r['net_win_rate_pct'],2)}% | {fmt(r['average_net_pct_notional'],4)}% | {fmt(r['profit_factor'])} | {r['active_utc_days']} | {r['unknown_candidates']} | {fmt(stress['average_net_pct_notional'],4)}% |")
    lines += ['', '共享钱包是只包含已核验路径的条件模拟：初始 1000 U，信号时单笔计划风险不超过当时已实现钱包余额的 0.5%，未成交与持仓合计计划风险不超过 1%；按可用逐仓保证金控制数量。未知路径未计入。', '',
              '| 20× 已知路径钱包 | 机会／模拟成交 | 净盈利笔数 | 期末钱包 | 收益率 | 已实现钱包余额最大回撤 | 亏损超过信号时余额 0.5% 的笔数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for holding in ('original', 'extended'):
        for cohort in labels:
            r = next(x for x in wallet['rows'] if x['period'] == holding and x['cohort'] == cohort and x['leverage'] == 20 and not x['reverse_ties'])
            losses = [x for x in wallet_detail if x['period'] == holding and x['cohort'] == cohort and x['leverage'] == '20'
                      and x['reverse_ties'] == 'False' and x['status'] == 'closed' and Decimal(x['net_pnl']) < -Decimal(x['reference_wallet']) * Decimal('.005')]
            lines.append(f"| {holds[holding]}／{labels[cohort]} | {r['known_opportunities']}／{r['simulated_trades']} | {r['net_wins']} | {fmt(r['final_wallet'],2)} U | {fmt(r['net_return_pct'],2)}% | {fmt(r['realized_wallet_drawdown_pct'],2)}% | {len(losses)} |")
    equal = all(next(x for x in summary['rows'] if x['holding_rule'] == hold and x['cohort'] == cohort and x['leverage'] == 10 and x['exit_slippage_pct'] == .05)[k]
                == next(x for x in summary['rows'] if x['holding_rule'] == hold and x['cohort'] == cohort and x['leverage'] == 20 and x['exit_slippage_pct'] == .05)[k]
                for hold in holds for cohort in labels for k in ('trades', 'net_wins', 'average_net_pct_notional'))
    lines += ['', f"逐笔检查：抽样独立重放 {len(tape['samples'])} 个候选；风险档案重取 {risk['verified_source_archives_redownloaded']} 份，逐路径复算 {risk['risk_paths_independently_checked']} 条；"
              f"持仓量复核 {oi['points_checked']} 点，其中 {oi['verified_points']} 点通过。汇总复核 {audit['candidate_classifications_checked']} 条候选状态和 {audit['summary_groups_checked']} 组；"
              f"钱包复核 {wallet_audit['scenarios_checked']} 个情景及 {wallet_audit['wallet_events_checked']} 个事件。", '',
              '模型假设每边 0.05% taker 手续费、每边 0.05% 不利滑点，资金费另计；先观察至少一秒，再至少等待一秒按下一笔公开成交作入场代理，退出信号后至少等待五秒。上述是模拟参考，并非真实盘口撮合或真实强平。', '',
              '0.5% 为信号时的计划风险，并非保证每笔实际亏损不超过 0.5%；入场后的价格变化、延迟退出和成本会使实际亏损超出预算。', '',
              '以上表格是聚合成交口径。后续独立抽样发现 3 个样本中 2 个的原始与聚合成交首秒金额及参考价存在分歧；保守改列未知后的单位收益和钱包结果见[原始成交抽样与敏感性](../第九十三轮_原始逐笔抽样交叉核验/原始聚合逐笔抽样结果.md)。', '',
              '在不改写本轮冻结结果的前提下，零成交分钟替代口径恢复了 196 个未知排名小时、剩余 44 个；恢复部分没有新增候选。[零成交小时替代口径](../第九十四轮_零成交分钟排名补充/零成交小时替代口径结果.md)', '',
              ('本次 10× 与 20× 的已核验单位路径汇总一致；不代表实际保证金或强平风险相同。' if equal else '本次 10× 与 20× 的已核验单位路径存在差异，具体结果见汇总文件；两者的实际保证金和强平风险也不能由代理模型代替。'), '',
              '2022 年为追补的历史检验，11 币是后来固定的，存在幸存者偏差，也无法排除此前其他研究接触该年度。持仓量的历史实时公布延迟尚未证明。钱包回撤只反映已实现余额，不包含持仓浮盈亏，无法作为真实账户最大回撤；未知候选及排名未知小时也使账户路径不完整。因此，本轮不能据此宣称达到完整账户和前瞻验证目标。', '',
              '[逐笔状态与单位账本](二零二二候选状态及单位账本.csv) · [汇总及滑点压力](二零二二一秒回测汇总.json) · [逐笔抽样核验](一秒逐笔独立样本核验.json) · [风险核验](风险来源与账本独立核验.json) · [钱包事件](共享钱包事件账本.csv)']
    (H / '二零二二一秒回测结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT90_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
