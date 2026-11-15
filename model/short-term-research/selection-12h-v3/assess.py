import csv,io
import cadence_engine as e

def main():
    rows=e.base.read(e.ROOT/'metrics.json');old=e.base.read(e.previous.ROOT/'official-metrics.json')
    allrows=old+rows;ix={(r['mode'],r['scenario']):r for r in allrows}
    pairs=[];decisions=[]
    for r in rows:
        ref=ix[r['mode'].replace('_12h__','_hourly__'),r['scenario']]
        valid=r['valid_for_comparison'] and ref['valid_for_comparison']
        pairs.append(dict(mode=r['mode'],name=r['name'],scenario=r['scenario'],valid=valid,
            hourly_cagr=ref['annualized_return_pct'],twelve_cagr=r['annualized_return_pct'],
            net_change_u=(r['return_pct']-ref['return_pct'])*10 if valid else None,
            cagr_change=r['annualized_return_pct']-ref['annualized_return_pct'] if valid and r['annualized_return_pct'] is not None else None,
            hourly_dd=ref['max_drawdown'],twelve_dd=r['max_drawdown'],
            hourly_trades=ref['core_trades'],twelve_trades=r['core_trades'],
            hourly_costs=ref['fees']+ref['slippage_cost'],twelve_costs=r['fees']+r['slippage_cost']))
    benchmark=ix['control_weekly__fixed1','main']
    for mode in e.NEW_NAMES:
        four=[ix[mode,s] for s in ('main','double','triple','delay')]
        valid=all(r['valid_for_comparison'] for r in four)
        screen=valid and all(r['return_pct']>0 and r['max_drawdown']<=15 for r in four) and four[0]['core_trades']>=30
        decisions.append(dict(mode=mode,complete_four=valid,historical_screen=screen,
            beats_weekly=valid and four[0]['annualized_return_pct']>benchmark['annualized_return_pct'],
            worst_dd=max(r['max_drawdown'] for r in four) if valid else None))
    primary='combined_12h__fixed1';p=ix[primary,'main'];oldp=ix['combined_hourly__fixed1','main']
    d=next(x for x in decisions if x['mode']==primary);passed=d['historical_screen'] and d['beats_weekly']
    headline='12小时版通过本轮历史门槛，仍需前瞻验证' if passed else '12小时频率比较已完成，主要候选尚未达到全部目标'
    explanation=(f"四因子1×从每小时改为每12小时：年化 {oldp['annualized_return_pct']:.2f}% → {p['annualized_return_pct']:.2f}%，"
        f"最大回撤 {oldp['max_drawdown']:.2f}% → {p['max_drawdown']:.2f}%，底仓交易 {oldp['core_trades']} → {p['core_trades']} 笔。"
        f"原周度动量1×年化 {benchmark['annualized_return_pct']:.2f}%、回撤 {benchmark['max_drawdown']:.2f}%。") if p['valid_for_comparison'] else '12小时主要候选数据/风险检查中止，完整收益不可比较。'
    result=dict(primary=primary,primary_success=bool(passed),headline=headline,explanation=explanation,decisions=decisions,pairs=pairs,
        total=len(rows),valid=sum(r['valid_for_comparison'] for r in rows),paper_changed=False,history_seen=True,
        fee_basis='USDT永续官方普通用户Taker单边0.05%，滑点估计单边0.05%，历史资金费逐笔；未读取账户VIP/BNB折扣。')
    e.base.dump(e.ROOT/'assessment.json',result)
    e.base.dump(e.ROOT/'all-metrics.json',allrows)
    cols=list(old[0]);buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(allrows)
    (e.ROOT/'metrics.csv').write_text('\ufeff'+buf.getvalue(),encoding='utf-8')
    lines=['每12小时换币：同数据、官方标准手续费对照',headline,explanation,'',result['fee_basis'],
        '2025-01-01至2026-04-26，共481天；期初1000U。每12小时在UTC00/12点（北京时间08/20点）重选；止损5分钟检查、动态杠杆每日评估，上限5份底仓数量。',
        '五种评分、选币门槛、仓位、止损、冷却和数据隔离均未修改。小时与周度结果完整保留。',
        '用户指定12小时，未搜索其他频率或根据回测结果调因子权重。历史已经研究，不是新样本外。','',
        '方案 | 小时年化% | 12小时年化% | 小时回撤% | 12小时回撤% | 底仓笔数(小时→12小时) | 手续费+滑点U(小时→12小时)']
    for x in pairs:
        if x['scenario']!='main':continue
        lines.append(f"{x['name']} | {x['hourly_cagr']:.2f} | {x['twelve_cagr']:.2f} | {x['hourly_dd']:.2f} | {x['twelve_dd']:.2f} | {x['hourly_trades']}→{x['twelve_trades']} | {x['hourly_costs']:.2f}→{x['twelve_costs']:.2f}")
    lines+=['','主要候选全部场景：','场景 | 手续费/单边 | 区间收益% | 年化% | 最大回撤%']
    for scenario,*_ in e.SCENARIOS:
        r=ix[primary,scenario]
        lines.append(f"{scenario} | {r['fee']*100:.3f}% | {r['return_pct']:.3f} | "+('不足一年' if r['annualized_return_pct'] is None else f"{r['annualized_return_pct']:.3f}")+f" | {r['max_drawdown']:.3f}")
    lines+=['','全部60条新增场景和原84条对照见metrics.csv。改善相对小时版，不等于优于周度基准或通过15%回撤目标。',
        '现有DailyMomentum模拟账户、配置和持仓保持不变，未接实盘。',
        '网页：http://127.0.0.1:8765/selection-research',
        '手续费依据：https://www.binance.com/en/support/faq/detail/360033544231']
    (e.ROOT/'研究结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(headline,explanation,flush=True)
    for x in pairs:
        if x['scenario']=='main':print(x,flush=True)

if __name__=='__main__':main()
