import csv,io,json
from collections import Counter
import pool_dynamic_engine as e
def main():
    rows=e.base.read(e.ROOT/'metrics.json');decisions=[];pairs=[];detail={}
    for mode in e.ALL_NAMES:
        q=[r for r in rows if r['mode']==mode];full=[r for r in q if not r['scenario'].startswith('prefix')];pre=[r for r in q if r['scenario'].startswith('prefix')]
        def gate(a):return all(r['valid_for_comparison'] and r['return_pct']>0 and r['max_drawdown']<=15 for r in a) and a[0]['core_trades']>=30
        decisions.append(dict(mode=mode,name=e.ALL_NAMES[mode],full_pass=gate(full),prefix_pass=gate(pre),full_valid=sum(r['valid_for_comparison'] for r in full),prefix_valid=sum(r['valid_for_comparison'] for r in pre),full_worst_dd=max(r['max_drawdown'] for r in full) if all(r['valid_for_comparison'] for r in full) else None,prefix_worst_dd=max(r['max_drawdown'] for r in pre) if all(r['valid_for_comparison'] for r in pre) else None))
        r=e.cached_run('2025-01-01','2026-04-26',mode);a=r['leverage_audit'];adds=[x for x in r['adjustments'] if x['action']=='add'];boost=[t for t in r['trades'] if t['layer']!='core']
        detail[mode]=dict(valid=r['valid_for_comparison'],add_decisions=len({(x['ts'],x['symbol']) for x in adds}),add_fills=len(adds),max_daily_actual=max((x['actual'] for x in a),default=1),boost_gross=sum(t['gross_pnl'] for t in boost),boost_net=sum(t['pnl'] for t in boost),boost_fees=sum(t['fees'] for t in boost),boost_slippage=sum(t['slippage'] for t in boost),boost_funding=sum(t['funding'] for t in boost),reduce_reasons=dict(Counter(x['reason'] for x in r['adjustments'] if x['action']=='reduce')),boost_by_exit={reason:{'lots':sum(t['reason']==reason for t in boost),'net':sum(t['pnl'] for t in boost if t['reason']==reason)} for reason in sorted({t['reason'] for t in boost})},boost_by_coin={s:sum(t['pnl'] for t in boost if t['symbol']==s) for s in sorted({t['symbol'] for t in boost})},coin_contributions=r['contributions'],unique_traded_symbols=len({t['symbol'] for t in r['trades']}))
    for selector in e.SELECTORS:
        for scenario,*_ in e.SCENARIOS:
            a=next(r for r in rows if r['mode']==selector+'__fixed1' and r['scenario']==scenario);b=next(r for r in rows if r['mode']==selector+'__tiered' and r['scenario']==scenario);valid=a['valid_for_comparison'] and b['valid_for_comparison']
            pairs.append(dict(selector=selector,scenario=scenario,valid=valid,annual_delta=b['annualized_return_pct']-a['annualized_return_pct'] if valid and a['annualized_return_pct'] is not None else None,net_delta_u=(b['return_pct']-a['return_pct'])*10 if valid else None,dd_delta=b['max_drawdown']-a['max_drawdown'] if valid else None,core_net_difference=b['core_pnl']-a['core_pnl'] if valid else None))
    primary=next(x for x in decisions if x['mode']=='slow_base__tiered');prefix=next(x for x in pairs if x['selector']=='slow_base' and x['scenario']=='prefix')
    assessment=dict(primary='slow_base__tiered',primary_full_passed=primary['full_pass'],primary_prefix_passed=primary['prefix_pass'],primary_prefix_improved=prefix['net_delta_u'] is not None and prefix['net_delta_u']>0,decisions=decisions,pairs=pairs,details=detail,scenarios=len(rows),valid=sum(r['valid_for_comparison'] for r in rows),full_period='2025-01-01..2026-10-31',prefix_period='2025-01-01..2026-04-26',headline='全池全区间证据不足：缺失标记价格使完整收益无效',history_seen=True,paper_changed=False)
    e.base.dump(e.ROOT/'assessment.json',assessment)
    if prefix['net_delta_u'] is not None and prefix['net_delta_u']<=0:
        assessment['headline']='公共子区间未改善收益；全区间因缺数无法完整评估'
        e.base.dump(e.ROOT/'assessment.json',assessment)
    cols=['mode','name','scenario','start','end','fee','delay_minutes','valid_for_comparison','annualized_return_pct','return_pct','max_drawdown','core_pnl','boost_pnl','core_trades','boost_trades','fees','slippage_cost','funding_cost','mean_exposure_pct','data_issues'];b=io.StringIO();w=csv.DictWriter(b,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows);(e.ROOT/'metrics.csv').write_text('\ufeff'+b.getvalue(),encoding='utf-8')
    lines=['全池自动选币 × 动态杠杆上限5倍',assessment['headline'],'','规则、数据和成本在新结果前固定；所有80场景保留，不按盈利改阈值。','全池沿用638个历史USDT现货归档，包括退市币；90个有效日、30日成交额中位数至少1000万U，流动性前20中按60日趋势跳过最近7日的风险调整评分选前2。保持原正动量做多规则；本轮扩展的是杠杆层，BTC/ETH多空仅作参考。','杠杆层完整复用上一轮：平时1倍，低波动1.5倍，10/30/60日方向/波动冲击/已知资金费确认上限5倍；底仓至少24小时且净浮盈、账户回撤<5%、加仓后组合计划止损风险<=2%。每天增加0.5份；条件下降减仓、账户回撤>=8%下根5分钟撤额外仓；4%价格止损及24小时额外仓冷却。','初始1000U，单边手续费0.1%/0.2%/0.3%，滑点0.05%，实际永续资金费。沿用同一日线和永续归档SHA256；不补造价格，不把现货价代替永续标记价。','全区间2025-01-01..2026-10-31；数据缺口前公共子区间2025-01-01..2026-04-26由旧缺口日期提前确定，不能替代全区间/独立样本外。','','公共子区间：方案 | 年化% | 净收益% | 回撤% | 四场景最差回撤% | 额外仓净利润U']
    for d in decisions:
        r=next(x for x in rows if x['mode']==d['mode'] and x['scenario']=='prefix');v=[r['annualized_return_pct'],r['return_pct'],r['max_drawdown'],d['prefix_worst_dd'],r['boost_pnl'] if r['valid_for_comparison'] else None];lines.append(' | '.join([r['name'],*[f'{x:.2f}' if x is not None else '无效' for x in v]]))
    lines+=['','完整区间缺数/风险中止：']
    for r in rows:
        if r['scenario']=='main' and r['data_issues']:lines.append(r['name']+' '+json.dumps(r['data_issues'],ensure_ascii=False))
    lines+=['','逐项增量：',json.dumps(pairs,ensure_ascii=False,indent=2),'','公共子区间诊断：',json.dumps(detail,ensure_ascii=False,indent=2),'','局限：已研究历史；全池与BTCETH参照的方向规则不同。7%抵押品压力线不是交易所精确历史强平规则；历史15%门槛及2%止损预算不保证未来。不能通过事后删币、提前清仓或择优结束日期修复数据。','当前模拟策略和进程保持原样。网页：http://127.0.0.1:8765/pool-dynamic','官方公开归档说明：https://github.com/binance/binance-public-data','标记价数据接口说明：https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data']
    (e.ROOT/'全池动态杠杆研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'decisions':decisions,'prefix_pairs':[x for x in pairs if x['scenario']=='prefix'],'valid':assessment['valid']},ensure_ascii=True))
if __name__=='__main__':main()
