"""Present the pre-fixed early-entry comparison without selecting a winning cell."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fmt(v, n=3):
    return '—' if v is None else f'{v:.{n}f}'


def main():
    z = json.loads((H / '前五分钟过滤对照.json').read_text(encoding='utf-8'))
    a = json.loads((H / '前五分钟过滤独立核验.json').read_text(encoding='utf-8'))
    w = json.loads((H / '共享钱包情景汇总.json').read_text(encoding='utf-8'))
    wa = json.loads((H / '共享钱包独立核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '前五分钟过滤对照.json')
    assert wa['all_checks_pass'] and wa['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    labels = {'base': '基础', 'distance': '距离', 'oi': '持仓量', 'oi_distance': '距离＋持仓量'}
    holds = {'original': '原柱末', 'extended': '延长一柱'}
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        wallet_detail = list(csv.DictReader(f))
    lines = ['# 突破发生在开柱前五分钟：固定规则对照', '',
             '将首次突破决定时间限定为 15 分钟柱开盘后的前五分钟；这项判断在一秒观察和延迟市价代理入场前可作出。下面同时展示不过滤和前五分钟，所有收益均已计入假设费用、滑点和资金费。', '',
             '| 时段／持有／过滤 | 不限时间：交易数／均值 | 前五分钟：交易／净盈利 | 净胜率 | 平均名义净收益 | 利润因子 | 活跃 UTC 日 | 前五分钟退出滑点 0.075% 均值 | 已列候选未知（保守） |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def get(period, holding, cohort, timing, slip):
        return next(x for x in z['rows'] if x['period'] == period and x['holding_rule'] == holding and x['cohort'] == cohort and x['leverage'] == 20 and x['timing'] == timing and x['exit_slippage_pct'] == slip)
    for period in ('2022', 'all'):
      for holding in ('original', 'extended'):
       for cohort in labels:
        base, early, stress = get(period, holding, cohort, 'all', .05), get(period, holding, cohort, 'early', .05), get(period, holding, cohort, 'early', .075)
        title = ('2022' if period == '2022' else '五段合计') + '／' + holds[holding] + '／' + labels[cohort]
        lines.append(f"| {title} | {base['known_trades']}／{fmt(base['mean_net_pct_notional'],4)}% | {early['known_trades']}／{early['net_wins']} | {fmt(early['net_win_rate_pct'],2)}% | {fmt(early['mean_net_pct_notional'],4)}% | {fmt(early['profit_factor'])} | {early['active_utc_days']} | {fmt(stress['mean_net_pct_notional'],4)}% | {early['unknown_candidates_conservative']} |")
    lines += ['', '2022 年已知路径共享钱包模拟（初始 1000 U，10×／20×逐仓情景，按信号时风险预算控制仓位；下表为 20×）：', '',
              '| 持有／过滤 | 机会／模拟成交 | 净盈利笔数 | 期末钱包 | 收益率 | 已实现钱包余额最大回撤 | 亏损超过信号时余额 0.5% 的笔数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for holding in ('original', 'extended'):
      for cohort in labels:
        r = next(x for x in w['rows'] if x['period'] == holding and x['cohort'] == cohort and x['leverage'] == 20 and not x['reverse_ties'])
        losses = [x for x in wallet_detail if x['period'] == holding and x['cohort'] == cohort and x['leverage'] == '20'
                  and x['reverse_ties'] == 'False' and x['status'] == 'closed' and Decimal(x['net_pnl']) < -Decimal(x['reference_wallet']) * Decimal('.005')]
        lines.append(f"| {holds[holding]}／{labels[cohort]} | {r['known_opportunities']}／{r['simulated_trades']} | {r['net_wins']} | {fmt(r['final_wallet'],2)} U | {fmt(r['net_return_pct'],2)}% | {fmt(r['realized_wallet_drawdown_pct'],2)}% | {len(losses)} |")
    lines += ['', f"逐笔和成本分组共复核 {a['paths_checked']} 条路径、{a['groups_checked']} 组；钱包另按事件复核 {wa['wallet_events_checked']} 项。未知候选采用原组保守数量，2022 年另有 240 个排名未知小时，不包含在表内候选数量中。", '',
              '规则在查看 2022 年收益前固定；此前项目已探索过其他执行规则下的首分钟过滤，故本次属于相关研究的延伸。2022 年此前可能被其他研究使用，且选币以后来固定的 11 币为准；五段还包含已反复研究的历史。多组对照具有探索性，不能依据表现最好的单元格声称稳健盈利。过去的正收益也不能证明未来盈利。', '',
              '以上为聚合成交口径；对两个原始与聚合数据分歧样本作保守处理后的前五分钟结果，见[原始成交抽样与敏感性](../第九十三轮_原始逐笔抽样交叉核验/原始聚合逐笔抽样结果.md)。', '',
              '另有零成交分钟替代口径恢复 196 个排名小时，余 44 个未知，恢复部分没有新增候选；这不改变本表。[替代口径核验](../第九十四轮_零成交分钟排名补充/零成交小时替代口径结果.md)', '',
              '手续费及滑点各为入场和退出每边 0.05%，退出压力仅改变退出滑点；一秒观察后还至少等待一秒入场。0.5% 是计划风险，价格跳动、延迟与成本可能使实际亏损超过预算。钱包结果跳过未知交易，余额回撤未包含浮动盈亏，不能判定真实账户最大回撤或交易所强平。', '',
              '公开的高频实盘实验发现，有利方向的市价订单可能遭遇更差的实际成交价；实验场所、品种及订单规模与本模型不完全相同，不能据此给本策略指定实际滑点，但支持继续做滑点压力检验。[Albers 等，实盘订单与延迟研究](https://ora.ox.ac.uk/objects/uuid%3Acdab1de2-7576-42e2-abae-ab12371eba76/files/rs4655j600)', '',
              '[冻结方案](冻结研究方案.md) · [逐笔结果](前五分钟过滤逐笔.csv) · [全部分组](前五分钟过滤对照.json) · [分组独立核验](前五分钟过滤独立核验.json) · [钱包事件](共享钱包事件账本.csv)']
    (H / '前五分钟过滤结果.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('EXT91_REPORT_WRITTEN', flush=True)


if __name__ == '__main__':
    main()
