import csv,io
import event_engine as e

def f(x):return '无效' if x is None else f'{x:.2f}'

def main():
    rows=e.base.read(e.ROOT/'metrics.json');old=e.base.read(e.cadence.ROOT/'all-metrics.json')
    allrows=old+rows;ix={(r['mode'],r['scenario']):r for r in allrows}
    pairs=[];decisions=[]
    for r in rows:
        ref=ix[r['mode'].replace('_event__','_12h__'),r['scenario']]
        valid=r['valid_for_comparison'] and ref['valid_for_comparison']
        pairs.append(dict(mode=r['mode'],name=r['name'],scenario=r['scenario'],valid=valid,
            previous_cagr=ref['annualized_return_pct'],event_cagr=r['annualized_return_pct'],
            previous_dd=ref['max_drawdown'],event_dd=r['max_drawdown'],
            previous_trades=ref['core_trades'],event_trades=r['core_trades'],
            previous_costs=ref['fees']+ref['slippage_cost'],event_costs=r['fees']+r['slippage_cost'],
            net_change_u=(r['return_pct']-ref['return_pct'])*10 if valid else None))
    benchmark=ix['control_weekly__fixed1','main']
    for mode in e.NEW_NAMES:
        full=[ix[mode,s] for s in ('main','double','triple','delay')]
        valid=all(r['valid_for_comparison'] for r in full)
        screen=valid and all(r['return_pct']>0 and r['max_drawdown']<=15 for r in full) and full[0]['core_trades']>=30
        decisions.append(dict(mode=mode,complete_four=valid,historical_screen=screen,
            beats_weekly=valid and full[0]['annualized_return_pct']>benchmark['annualized_return_pct'],
            worst_dd=max(r['max_drawdown'] for r in full) if valid else None))
    primary='combined_event__fixed1';p=ix[primary,'main'];ref=ix['combined_12h__fixed1','main']
    d=next(x for x in decisions if x['mode']==primary);passed=d['historical_screen'] and d['beats_weekly']
    headline='卖出后补位版通过本轮历史门槛，仍需前瞻验证' if passed else '卖出后补位比较已完成，主要候选尚未达到全部目标'
    explanation=(f"四因子1×从每12小时换币改为卖出后补位：年化 {f(ref['annualized_return_pct'])}% → {f(p['annualized_return_pct'])}%，"
        f"最大回撤 {f(ref['max_drawdown'])}% → {f(p['max_drawdown'])}%，底仓交易 {ref['core_trades']} → {p['core_trades']} 笔。"
        f"原周度动量1×年化 {f(benchmark['annualized_return_pct'])}%、回撤 {f(benchmark['max_drawdown'])}%。") if p['valid_for_comparison'] else '主要候选遇到持仓数据缺失或抵押品压力，完整区间指标无效；不虚构退出价格。'
    result=dict(primary=primary,headline=headline,explanation=explanation,primary_success=bool(passed),pairs=pairs,decisions=decisions,
        total=len(rows),valid=sum(r['valid_for_comparison'] for r in rows),history_seen=True,paper_changed=False,
        data_issues=[dict(mode=r['mode'],scenario=r['scenario'],issues=r['data_issues']) for r in rows if not r['valid_for_comparison']])
    e.base.dump(e.ROOT/'assessment.json',result);e.base.dump(e.ROOT/'all-metrics.json',allrows)
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=list(old[0]),extrasaction='ignore');w.writeheader();w.writerows(allrows)
    (e.ROOT/'metrics.csv').write_text('\ufeff'+buf.getvalue(),encoding='utf-8')
    lines=['卖出后按排行榜补位：同数据、同成本研究',headline,explanation,'',
        '区间2025-01-01至2026-04-26，共481天；期初1000U。单边官方普通用户USDT永续Taker手续费0.05%，滑点估计0.05%，历史资金费逐笔。账户VIP/BNB优惠未读取，历史手续费优惠未逐期复原。',
        '两仓独立：初始按最高合格名次建仓；排名下降或到固定时间不卖出；止损/择时退出后，下一个可执行5分钟时点从未持有、数据有效、冷却及风控允许的币中，按最新已知排行榜从高到低补空位。',
        '没有合格币保留现金；有空位期间继续检查入场资格。方向退出仍UTC00/12点，止损每5分钟，杠杆每日评估上限5份底仓。',
        '已持仓币离开资格池后仍用自身已结束小时价格计算30日动量，不因落选被当作零动量卖出。',
        '所有潜在补位候选都提前获取同一历史区间内执行数据；新增归档与旧归档重叠部分校验一致。缺失后的因果隔离规则保留，持仓缺价仍使路径无效。','',
        '方案 | 12小时年化% | 补位版年化% | 12小时回撤% | 补位版回撤% | 底仓笔数 | 手续费+滑点U']
    for x in pairs:
        if x['scenario']=='main':lines.append(f"{x['name']} | {f(x['previous_cagr'])} | {f(x['event_cagr'])} | {f(x['previous_dd'])} | {f(x['event_dd'])} | {x['previous_trades']}→{x['event_trades']} | {f(x['previous_costs'])}→{f(x['event_costs'])}")
    lines+=['','主要候选完整场景：','场景 | 手续费/单边 | 有效 | 区间收益% | 年化% | 最大回撤%']
    for scenario,*_ in e.SCENARIOS:
        r=ix[primary,scenario]
        lines.append(f"{scenario} | {r['fee']*100:.3f}% | {r['valid_for_comparison']} | {f(r['return_pct'])} | {f(r['annualized_return_pct']) if r['elapsed_days']>=365 else '不足一年'} | {f(r['max_drawdown'])}")
    lines+=['','本轮新增4版本×6场景=24条；原小时、12小时、周度144条保留，合计28版本168条。',
        '规则由用户明确指定，在新增结果产生前冻结；没有根据结果继续修改权重、窗口和止损。历史已被反复研究，不能称为独立样本外。',
        '现有DailyMomentum模拟进程与配置未改变，未接真实账户。',
        '网页：http://127.0.0.1:8765/selection-research',
        '手续费来源：https://www.binance.com/en/support/faq/detail/360033544231']
    (e.ROOT/'研究结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(headline,explanation,flush=True)
    for x in pairs:
        if x['scenario']=='main':print(x,flush=True)

if __name__=='__main__':main()
