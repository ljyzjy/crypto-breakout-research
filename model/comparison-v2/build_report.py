import json
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
LABELS = {"SpotTrendV1":"原小时突破", "DailyDonchian":"55/20 日通道突破",
          "DailyMA":"20/60 日均线", "DailyMomentum":"30 日动量", "DailyBollinger":"布林带回归"}
NEIGHBORS = {"DailyDonchian":["DonchianLow","DonchianHigh"], "DailyMA":["MALow","MAHigh"],
             "DailyMomentum":["MomentumLow","MomentumHigh"], "DailyBollinger":["BollingerLow","BollingerHigh"]}


def main():
    rows = json.loads((OUT/"all_metrics.json").read_text())
    frozen = json.loads((OUT/"frozen_selection.json").read_text())
    lookup = {(r['scenario'],r['strategy']):r for r in rows}
    def get(name, window, fee=.001, suffix=""):
        return lookup[(f"{window}-fee{fee:.3f}{suffix}",name)]
    order = [r['strategy'] for r in frozen['ranking']] + ['SpotTrendV1']
    decision = []
    for rank in frozen['ranking']:
        name = rank['strategy']
        base = get(name,'evaluation')
        stress = get(name,'evaluation',.002)
        neighbors = [get(n,'evaluation',.002,'-neighbors') for n in NEIGHBORS[name]]
        conditions = {
            'early_gate': rank['eligible_early'],
            'evaluation_base_positive': base['profit'] > 0,
            'evaluation_double_fee_positive': stress['profit'] > 0,
            'each_later_year_positive': all(get(name,y)['profit'] > 0 for y in ['2025','2026']),
            'drawdown_under_10pct': base['dd_pct'] <= 10 and stress['dd_pct'] <= 10,
            'evaluation_trades_at_least_30': base['trades'] >= 30,
            'both_neighbors_positive': all(n['profit'] > 0 for n in neighbors),
        }
        concentration = (base['top3_gross_profit_share'] or 0) > .5
        one_pair = any(p <= 0 for p in base['pair_profit'].values())
        decision.append({'strategy':name, 'conditions':conditions, 'passes_gates':all(conditions.values()),
                         'concentration_warning':concentration, 'pair_warning':one_pair})
    (OUT/'decision.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    eligible = [d for d in decision if d['passes_gates']]
    lead = eligible[0]['strategy'] if eligible else None
    report = ['# 数字货币现货策略比较：固定规则、相同数据与费用', '',
              '数据截至 2026-10-31。结果来自本机 Freqtrade 2026.10，全部为历史仿真。', '',
              f"结论：{'优先进入前瞻模拟的是 '+LABELS[lead]+'，仍未验证真实成交与持续收益。' if lead else '没有候选同时通过预设条件，不应仅凭本轮收益直接启用真钱。'}", '',
              '## 比较口径', '',
              '两币 BTC/USDT、ETH/USDT；1,000 USDT 初始资金，每笔 100 USDT、最多两笔；所有主动策略相同 4% 止损与保护，保留大部分闲置现金；各区间独立重置，连续区间另行回测。',
              '收益均为完整账户累计收益、非年化。回撤来自逐小时钱包市值，含未实现盈亏，不是只用已平仓利润；无法代表逐笔或小时内极值回撤。',
              '新策略从原小时数据聚合完整 UTC 日线，日收盘确认、下一小时开盘执行。原基线按小时决策。框架成熟不等于本次参数或实现具有经过认证的实盘业绩。', '',
              '## 先固定的早期排序', '',
              f"排序冻结时间：{frozen['frozen_at_utc']}。仅使用 2023/2024，后段结果未用于改变顺序。", '',
              '| 策略 | 2023 账户收益 | 2024 账户收益 | 双倍费用最差早期年 | 两年交易数 | 早期门槛 |',
              '|---|---:|---:|---:|---:|---|']
    for rank in frozen['ranking']:
        name=rank['strategy']
        report.append(f"| {LABELS[name]} | {get(name,'2023')['return_pct']:.2f}% | {get(name,'2024')['return_pct']:.2f}% | {rank['worst_year_stress_return']:.2f}% | {rank['early_base_trades']} | {'通过' if rank['eligible_early'] else '未通过'} |")
    report += ['', '## 所有方案的后段表现', '',
               '| 策略 | 2025 收益 | 2026年1–10月收益 | 连续评估期收益 | 连续评估期回撤 | 交易数 |',
               '|---|---:|---:|---:|---:|---:|']
    for name in order:
        s=get(name,'evaluation')
        report.append(f"| {LABELS[name]} | {get(name,'2025')['return_pct']:.2f}% | {get(name,'2026')['return_pct']:.2f}% | {s['return_pct']:.2f}% | {s['dd_pct']:.2f}% | {s['trades']} |")
    report += ['', '每边 0.1% 费用；分年与连续结果不同，因为跨年持仓与各区间重置不同，不能简单相加。', '',
               '## 费用与成交细化', '', '| 策略 | 每边0.1% | 每边0.2% | 每边0.3% | 5分钟细化、0.1% |', '|---|---:|---:|---:|---:|']
    for name in order:
        report.append(f"| {LABELS[name]} | {get(name,'evaluation')['return_pct']:.2f}% | {get(name,'evaluation',.002)['return_pct']:.2f}% | {get(name,'evaluation',.003)['return_pct']:.2f}% | {get(name,'evaluation',.001,'-5m')['return_pct']:.2f}% |")
    report += ['', '压力费率是成本敏感性场景，未实现精确盘口冲击模型。5 分钟细化也不等于真实逐笔成交。', '',
               '## 参数邻域，仅作诊断', '', '| 策略 | 低窗口版本收益 | 原参数收益 | 高窗口版本收益 |', '|---|---:|---:|---:|']
    for name in order[:-1]:
        low,high=NEIGHBORS[name]
        report.append(f"| {LABELS[name]} | {get(low,'evaluation',.002,'-neighbors')['return_pct']:.2f}% | {get(name,'evaluation',.002)['return_pct']:.2f}% | {get(high,'evaluation',.002,'-neighbors')['return_pct']:.2f}% |")
    report += ['', '以上均为连续评估期、每边0.2%。八个变体在运行前写入方案，未选择其中最高收益版本替代原参数；没有据结果补加参数搜索。', '',
               '## 收益分散程度', '', '| 策略 | BTC贡献 USDT | ETH贡献 USDT | 最好三笔占毛盈利 | 最差已平仓利润月 USDT |', '|---|---:|---:|---:|---:|']
    for name in order:
        s=get(name,'evaluation')
        report.append(f"| {LABELS[name]} | {s['pair_profit'].get('BTC/USDT',0):.2f} | {s['pair_profit'].get('ETH/USDT',0):.2f} | {(s['top3_gross_profit_share'] or 0):.1%} | {s['worst_month_profit']:.2f} |")
    report += ['', '## 现金和买入持有基准', '', '| 区间 | 现金收益 | 20%初始暴露买入持有收益 | 买入持有权益回撤 |', '|---|---:|---:|---:|']
    baselines=[]
    for window in ['2023','2024','2025','2026','evaluation','full']:
        s=get('SpotTrendV1',window)
        start,end=pd.Timestamp(s['start'],tz='UTC'),pd.Timestamp(s['end'],tz='UTC')
        holdings=[]
        for pair in ['BTC','ETH']:
            data=pd.read_feather(ROOT/f'user_data/data/binance/{pair}_USDT-1h.feather')
            data=data[(data.date>=start)&(data.date<=end)].set_index('date')
            holdings.append(100/(data.open.iloc[0]*1.001)*data.close)
        equity=800+holdings[0]+holdings[1]
        final=800+(holdings[0].iloc[-1]+holdings[1].iloc[-1])*.999
        result={'window':window,'return_pct':(final/1000-1)*100,
                'dd_pct':float((1-equity/equity.cummax()).max())*100}
        baselines.append(result)
        report.append(f"| {window} | 0% | {result['return_pct']:.2f}% | {result['dd_pct']:.2f}% |")
    pd.DataFrame(baselines).to_csv(OUT/'benchmarks.csv',index=False)
    report += ['', '买入持有期初各用100 USDT含买入费买 BTC/ETH，保留800现金，期末扣卖出费；回撤按持仓市值，不预扣卖出费。初始资金配置相同，持续市场暴露并不相同。仅有收益更高不能声称风险调整后显著更优。', '',
               '## 筛选条件逐项结果', '']
    meanings={'early_gate':'早期筛选','evaluation_base_positive':'评估期基础费用盈利','evaluation_double_fee_positive':'双倍费用盈利',
              'each_later_year_positive':'后段两个年度均盈利','drawdown_under_10pct':'回撤不超过10%',
              'evaluation_trades_at_least_30':'评估期至少30笔','both_neighbors_positive':'两侧参数邻域盈利'}
    for d in decision:
        failed=[meanings[k] for k,v in d['conditions'].items() if not v]
        report.append(f"- {LABELS[d['strategy']]}：{'通过门槛，只列为优先模拟候选' if d['passes_gates'] else '未通过：'+'、'.join(failed)}。" +
                      (' 最好三笔盈利集中度超过50%。' if d['concentration_warning'] else '') +
                      (' 至少一个币种贡献非正。' if d['pair_warning'] else ''))
    report += ['', '## 防止过拟合：实际做了什么、仍缺什么', '',
               '本轮只有四个候选、一套共同风控、八个预先固定的诊断变体。规则与数据哈希见 fingerprint.json，早期顺序见 frozen_selection.json，所有结果（含失败者）保留，未使用 Hyperopt。',
               '此前已经看过同一段市场历史，本轮仍存在策略选择与重复检验风险；不能把后段收益当作全新独立样本外证据。邻域正收益也不构成统计显著性检验。两币高度相关，交易数不能当作同等数量的独立样本。',
               '初始样本只包括当前仍活跃的 BTC/ETH，对其他币种和退市币没有代表性；行情缺口与以前相同。回测使用当下交易规则元数据，历史最小订单规则没有逐日重建。',
               '通过门槛后的下一步是固定策略不改参数、进行至少4–8周前瞻模拟并等待足够完整交易。应记录全部信号/成交差异、网络故障和持仓核对；低频策略可能需要数月才积累足够样本。',
               '没有启动新模拟或任何实盘；原交易 API 地区限制也未因回测而解除。', '',
               '## 参考与追溯', '',
               '- 规则与一手来源：PROTOCOL.md。',
               '- 全量数值：all_metrics.csv / all_metrics.json；原始引擎输出：results/。',
               '- 每个运行目录均保存命令、日志、引擎 ZIP 和指标。',
               '- 代码时间一致性：verify_candidates.py；引擎前视与递归检查日志保存在本目录。',
               '- 最终运行状态及检查细节：VALIDATION.md。']
    (OUT/'COMPARISON_REPORT.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps({'preferred_forward_paper_candidate':lead,'decisions':decision},indent=2))


if __name__ == '__main__':
    main()
