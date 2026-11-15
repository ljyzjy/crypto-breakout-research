import csv,json
import pool_engine as p

def main():
    rows=p.old.base.read(p.ROOT/'metrics.json')
    def get(mode,window='later',fee=.001,delay=0):return next(r for r in rows if r['mode']==mode and r['window']==window and r['fee']==fee and r['resolution']=='5m' and r['delay_minutes']==delay)
    base=get('pool_control');decisions=[]
    for mode in p.VARIANTS:
        r=get(mode);stress=[get(mode,fee=f) for f in (.002,.003)]+[get(mode,delay=5)]
        gates={'positive_and_better_pool_cagr':r['annualized_return_pct']>max(0,base['annualized_return_pct']),
               'drawdown15':r['max_drawdown']<=15,'positive2025':get(mode,'2025')['return_pct']>0,'positive2026':get(mode,'2026')['return_pct']>0,
               'at_least30trades':r['trade_count']>=30,'stress_positive_dd15':all(x['return_pct']>0 and x['max_drawdown']<=15 for x in stress),
               'valid_paths':all(x['valid_for_comparison'] and x['ledger_error']<1e-7 and x['cash_min']>=0 for x in rows if x['mode']==mode)}
        contrib=sorted(r['contributions'].items(),key=lambda x:-x[1])
        decisions.append({'mode':mode,'name':r['name'],'main':r,'gates':gates,'passes':all(gates.values()),'max_stress_dd':max(x['max_drawdown'] for x in stress),'top_contributors':contrib[:5]})
    passed=[d for d in decisions if d['passes']]
    selected=max(passed,key=lambda d:d['main']['annualized_return_pct']) if passed else None
    slow=get('pool_slow_selection');combo=get('pool_combined')
    headline='全池改进已转正：较慢选币评分提升收益，组合版回撤更低'
    note=f"较慢评分年化{slow['annualized_return_pct']:.2f}%、回撤{slow['max_drawdown']:.2f}%；组合版年化{combo['annualized_return_pct']:.2f}%、回撤{combo['max_drawdown']:.2f}%。均通过本轮历史门槛，仍未超过BTC/ETH原策略6.23%的年化；当前模拟未切换。"
    result={'headline':headline,'note':note,'decisions':decisions,'selected_mode':selected['mode'] if selected else None,'fixed_scenarios':42,'history_seen':True,'paper_changed':False,
            'comparators':{'original_BTC_ETH_cagr':6.2254221801522975,'BTC_ETH_3U_cagr':8.873274877630474},
            'scope':'Ranking single changes is retrospective research selection; do not treat passing historical gates as a proven profitable live strategy.'}
    p.old.base.dump(p.ROOT/'assessment.json',result)
    fields=['mode','name','window','start','end','resolution','fee','delay_minutes','annualized_return_pct','return_pct','max_drawdown','trade_count','mean_exposure_pct','gross_pnl','fees','slippage_cost','valid_for_comparison']
    with (p.ROOT/'metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    sources=[
      {'title':'原全池逐笔账本','url':'/api/coin-lab/evidence/baseline_trade_diagnosis.csv','role':'亏损分解与假设形成；不是因果收益预测'},
      {'title':'本轮固定协议','url':'/api/coin-lab/evidence/protocol.json','role':'四个独立改动及唯一组合，42个固定场景'},
      {'title':'AQR: The Case for Momentum Investing','url':'https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/The-Case-for-Momentum-Investing.pdf','used':'较长趋势与跳过近期收益的设计思路','limit':'原文主要股票12个月跳过1个月；本地60日/7日为一次事先固定适配，不是文献证明数字货币最优'},
      {'title':'Man Group: Active Risk Management','url':'https://www.man.com/insights/active-risk-management-in-practice','used':'动量风险过滤与波动风险分配原则','limit':'不证明BTC30日过滤或2sigma止损能改善本策略；本轮以独立回测检验'},
      {'title':'Binance public data','url':'https://github.com/binance/binance-public-data','role':'同源公开月归档、逐文件SHA256；旧数据保持不变'}]
    p.old.base.dump(p.ROOT/'sources.json',sources)
    lines=['全池自动选币：亏损诊断与固定改进结果','',headline,note,'',
      '主比较：2025-01-01至2026-10-31，669天，初始1000U，单边手续费0.1%+滑点0.05%，5分钟执行。年化按账户总净值，含闲置现金。','',
      '亏损的主要来源（原全池2U）：',
      '成本前亏损42.39U，手续费25.57U，滑点12.79U，合计净亏80.75U。199/271笔价格止损，净亏325.84U；另19笔日动量退出净赚31.91U、53笔周度集合退出净赚213.18U，三类合计精确对账。',
      '止损持有时间中位19.75小时；197笔交易入场时日波动率>=4%。固定4%止损与高波动交易的兼容性不足是待检验机制，止损账本本身不能证明应取消止损。',
      '同周止损后重买136笔净亏26.14U；BTC30日方向非正入场132笔净亏59.32U；两组重叠，不相加当预计收益。最近7日上涨入场组更差，因此没有机械加7日正动量入场条件。','',
      '方案 | 账户年化 | 累计净收益 | 最大回撤 | 交易 | 压力最高回撤 | 门槛']
    for d in decisions:
        r=d['main'];lines.append(f"{r['name']} | {r['annualized_return_pct']:+.2f}% | {r['return_pct']:+.2f}% | {r['max_drawdown']:.2f}% | {r['trade_count']} | {d['max_stress_dd']:.2f}% | {'通过' if d['passes'] else '未通过'}")
    lines+=['','固定改动：',
      '选币：流动性池仍为原top20，周度选2；评分改为(C[d-7]/C[d-60]-1)/20日波动率，要求该收益和原30日动量都为正。d是上一完整日。',
      '市场择时：只在BTC30日收益>0时允许新开仓，不强制卖出现有仓位。',
      '重试择时：亏损止损后该币等到下一周一，原6小时冷却和全局暂停仍保留。',
      '分仓风险：止损距离clip(2sigma,4%,20%)，入场金额min(200,4/止损距离)U。每仓计划止损风险4U；止损在入场固定，不事后放宽。跳空/费用可能使实际损失超过计划。',
      '组合：上述四项全加；在独立改动收益出现前已经写入协议，未根据结果删改组件。','',
      '跨年与压力：']
    for mode in ('pool_slow_selection','pool_combined'):
        lines.append(p.VARIANTS[mode]['name'])
        for window,fee,delay in [('2025',.001,0),('2026',.001,0),('later',.002,0),('later',.003,0),('later',.001,5)]:
            r=get(mode,window,fee,delay);lines.append(f"  {window} fee={fee} delay={delay}: 净收益{r['return_pct']:+.2f}%，回撤{r['max_drawdown']:.2f}%")
        r=get(mode);top=sorted(r['contributions'].items(),key=lambda x:-x[1])[:5]
        lines.append('  主要净贡献：'+', '.join(f'{s} {v:+.2f}U' for s,v in top))
        lines.append(f"  前三大盈利交易占全部正利润{r['top3_profit_share']:.2f}%；平均实际仓位{r['mean_exposure_pct']:.2f}%。")
    lines+=['','结论与边界：',
      '本轮较慢评分方案从负年化转为正年化，回撤下降；市场过滤、延后重试、波动止损各自减少亏损，但单独仍未转正。不能把全部改善归因于降低费用或放宽止损。',
      '较慢评分的成本前盈亏从−42.39U升至+139.25U；费用和滑点从38.36U降至31.40U。因此188.60U净改善中，181.64U来自价格路径差异，6.96U来自成本减少。该差额是两套完整模拟的账本分解，不等于未来可重复的因果效应。',
      '较慢评分的前三笔盈利交易占全部正利润34.97%，组合版为38.59%，仍需观察盈利是否集中于少数行情。没有据此删除币种或重新调参。',
      '较慢评分主区间仍低于BTC/ETH原策略6.23%和3U候选8.87%的账户年化。预定组合更低回撤但收益也更低；并非改动越多越好。',
      '不在看到结果后继续提高仓位把回测收益推过基准。可将较慢评分和组合版留作后续独立前瞻候选；当前模拟账户及四组合观察均保持不变。',
      '全638币日线、排除规则与时间范围未变。新增规则触及的执行月份采用同源归档补齐，旧执行数据逐行相同，旧文件指纹保持。没有利用已下载币名单限制选择。各跨年子区间均独立从1000U空仓开始，因此交易数及收益不要求直接相加等于连续主区间。',
      '历史已在多轮研究中被看过；通过门槛不能等同新的样本外证据。15%是历史收盘回撤筛选标准，不能保证未来/盘中风险。波动止损仍会遇到跳空和执行误差。','',
      '网页：http://127.0.0.1:8765/coin-lab','所有亏损场景保留；协议、源码、CSV、信息时点及账本验证均在本目录。']
    (p.ROOT/'全池选币亏损诊断与改进报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'headline':headline,'rows':[{'mode':d['mode'],'cagr':d['main']['annualized_return_pct'],'passes':d['passes'],'top':d['top_contributors']} for d in decisions]},ensure_ascii=True))

if __name__=='__main__':main()
