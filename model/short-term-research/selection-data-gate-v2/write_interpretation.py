"""Evidence-bounded narrative from completed official-fee results."""
import json
import availability_engine as e

def n(v):return '—' if v is None else f'{v:.2f}'

def main():
    rows=e.base.read(e.ROOT/'official-metrics.json')
    assessment=e.base.read(e.ROOT/'official-assessment.json')
    ix={(r['mode'],r['scenario']):r for r in rows}
    b=ix['control_weekly__fixed1','main'];a=ix['combined_hourly__fixed1','main']
    h=ix['control_hourly__fixed1','main']
    cb=ix['control_weekly__fixed1','2025'];ca=ix['combined_hourly__fixed1','2025']
    hourly=[r for r in rows if r['scenario']=='main' and '_hourly__' in r['mode']]
    findings=[
        f"原周度动量1×：年化 {n(b['annualized_return_pct'])}%，回撤 {n(b['max_drawdown'])}%；仅改为小时重排：年化 {n(h['annualized_return_pct'])}%，回撤 {n(h['max_drawdown'])}%。",
        f"主要候选四因子小时1×：年化 {n(a['annualized_return_pct'])}%，回撤 {n(a['max_drawdown'])}%，底仓交易 {a['core_trades']} 笔。",
        f"2025年同一官方费率下，四因子小时版成本前 {n(ca['gross_pnl'])} U，手续费 {n(ca['fees'])} U，滑点 {n(ca['slippage_cost'])} U，净资金费 {n(ca['funding_cost'])} U；原周度动量成本前 {n(cb['gross_pnl'])} U，手续费+滑点 {n(cb['fees']+cb['slippage_cost'])} U。",
        '小时数据更新不代表因子有小时级预测能力。本轮30/60日信号直接按小时排名换仓，产生短持仓和高换手；因子权重、阈值、止损与杠杆规则均未据结果再调。',
        '上限5×只限制单币相对底仓数量；不是全账户始终5倍。额外仓按实际名义额收费并计入资金费，完整配对结果保留。']
    if all(r['return_pct']<0 for r in hourly):
        findings.append('本轮10个小时版本（5种评分×1×/动态5×）在官方标准手续费下的主区间净收益全部为负。')
    assessment['findings']=findings
    assessment['fee_basis']='官方普通用户USDT永续Taker单边0.05%；滑点估计单边0.05%；历史资金费逐笔。未读取账户折扣，未逐期重建历史费率。'
    assessment['explanation']+=' '+findings[0]+' '+findings[1]+' 基础手续费已按用户要求改为官方普通用户Taker 0.05%/单边。'
    assessment['next_direction']='保留每小时监测能力；下一轮应先单独检验排名缓冲、换币收益门槛或持续确认对换手的作用，预先固定一个实验，不在本轮失败后继续调权重和窗口。此前已有排名缓冲研究，需按同一新费率与小时机制重新验证增量，不能直接宣称有效。'
    e.base.dump(e.ROOT/'official-assessment.json',assessment)
    validation=e.base.read(e.ROOT/'validation.json')
    lines=['全池小时选币与官方标准手续费：研究结果',assessment['headline'],assessment['fee_basis'],'',
        '统一区间：2025-01-01 至 2026-04-26，共481天；期初1000U，所有年化按总账户净值计算。',
        '当前研究14版本×6场景=84；保留缺失隔离前84场景和旧成本84场景。压力手续费为0.10%与0.15%，另测延迟5分钟。',
        '数据可用性修订：已结束永续成交柱有交易而标记价缺失，才触发统一隔离，不按未来收益删币。币安人生首个可知缺失时点为2026-04-01 00:05 UTC，下一次小时选币01:00起排除；此前历史完整保留。归档缺失不等于历史线上行情中断。',
        '',*findings,'','完整主区间结果（官方标准手续费）：',
        '策略 | 1×年化% | 1×最大回撤% | 动态上限5×年化% | 动态上限5×最大回撤%']
    for selector in ('control_weekly','combined_weekly','control_hourly','liquidity_hourly','continuity_hourly','residual_hourly','combined_hourly'):
        x,y=ix[selector+'__fixed1','main'],ix[selector+'__tiered','main']
        lines.append(' | '.join([e.SELECTORS[selector],n(x['annualized_return_pct']),n(x['max_drawdown']),n(y['annualized_return_pct']),n(y['max_drawdown'])]))
    lines+=['','主要候选的全部场景：','场景 | 单边手续费 | 区间收益% | 年化% | 最大回撤%']
    for scenario,*_ in e.base.read(e.ROOT/'official-protocol.json')['cost_scenarios']:
        r=ix['combined_hourly__fixed1',scenario]
        lines.append(' | '.join([scenario,str(r['fee']),n(r['return_pct']),n(r['annualized_return_pct']),n(r['max_drawdown'])]))
    lines+=['','规则来源与改写：']+[s['name']+'：'+s['use']+' '+s['url'] for s in e.base.read(e.ROOT/'sources.json')['sources']]
    lines+=['','验证记录：',*validation['checks'],'',
        '2025年配对日收益差的7日区块重采样（1000次、固定种子；单位bp/日，不是年化区间，也不是独立样本外）：',
        json.dumps(validation['bootstrap']['pairs'],ensure_ascii=False,indent=2),'',
        assessment['next_direction'],
        '现有DailyMomentum模拟进程和配置保持不变；未接真实账户。过去历史已被重复研究，本轮没有新的未触碰样本；历史15%回撤门槛不能保证未来。',
        '7%抵押品压力线是保守研究约束，不是精确复原的交易所历史强平规则。',
        '网页：http://127.0.0.1:8765/selection-research',
        '官方费率依据：https://www.binance.com/en/support/faq/detail/360033544231']
    (e.ROOT/'研究结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(findings),flush=True)

if __name__=='__main__':main()
