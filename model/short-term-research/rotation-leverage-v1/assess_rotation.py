import csv,json
import rotation_engine as e

def main():
    rows=e.base.read(e.ROOT/'metrics.json');decisions=[]
    def get(mode,venue,lev,scenario):return next(r for r in rows if r['mode']==mode and r['venue']==venue and r['leverage']==lev and r['scenario']==scenario)
    for venue in ('spot','perp'):
        for lev in range(1,11) if venue=='perp' else (1,):
            control=get('slow_base',venue,lev,'main')
            for mode in e.NAMES:
                a=[get(mode,venue,lev,s) for s,_,_,_,_ in e.SCENARIOS];r=a[0]
                gates={'all_paths_valid':all(x['valid_for_comparison'] for x in a),'all_returns_positive':all(x['return_pct'] is not None and x['return_pct']>0 for x in a),'all_dd15':all(x['max_drawdown'] is not None and x['max_drawdown']<=15 for x in a),'main_30_trades':r['trade_count']>=30}
                valid=r['valid_for_comparison'] and control['valid_for_comparison']
                decisions.append({'mode':mode,'name':e.NAMES[mode],'venue':venue,'leverage':lev,'passes':all(gates.values()),'gates':gates,'main':r,'worst_dd':max([x['max_drawdown'] for x in a if x['max_drawdown'] is not None],default=None),'all_valid':gates['all_paths_valid'],'delta_net_vs_slow':(r['final_equity']-control['final_equity']) if valid else None,'delta_cost_vs_slow':sum(r[k]-control[k] for k in ('fees','slippage_cost','funding_cost')) if valid else None,'delta_gross_vs_slow':r['gross_pnl']-control['gross_pnl'] if valid else None})
    eligible=[d for d in decisions if d['passes']];best=max(eligible,key=lambda x:x['main']['annualized_return_pct']) if eligible else None
    spot=[d for d in decisions if d['venue']=='spot'];p1=[d for d in decisions if d['venue']=='perp' and d['leverage']==1]
    headline='两项改动未提高现货净收益；全池永续存在数据缺口'
    note=(f"按固定历史门槛，最高年化为{best['name']} · {'永续' if best['venue']=='perp' else '现货'} {best['leverage']}倍：{best['main']['annualized_return_pct']:.2f}%，回撤{best['main']['max_drawdown']:.2f}%。历史已被研究，仍需前瞻验证；当前模拟未切换。" if best else '没有版本通过全部固定门槛；所有失败和风险中止结果均保留，当前模拟未切换。')
    coverage_note='币安人生早期永续成交价与资金费可得，但标记价归档仅从2026-10-15开始；官方历史接口返回451地区限制，未能补齐。涉及该缺口的全池场景停止，不能给出完整区间年化。没有剔除该币或用现货价代替。'
    note+=' '+coverage_note
    result={'headline':headline,'note':note,'coverage_note':coverage_note,'decisions':decisions,'best':best,'total':268,'invalid':sum(not r['valid_for_comparison'] for r in rows),'selected_mode':best['mode'] if best else 'slow_base','selected_venue':best['venue'] if best else 'perp','selected_leverage':best['leverage'] if best else 1,'history_seen':True,'paper_changed':False}
    e.base.dump(e.ROOT/'assessment.json',result)
    fields=['mode','name','venue','leverage','scenario','start','end','fee','delay_minutes','resolution','annualized_return_pct','return_pct','max_drawdown','intrabar_simultaneous_low_stress_dd','trade_count','mean_exposure_pct','gross_pnl','fees','slippage_cost','funding_cost','skip_count','minimum_collateral_ratio_pct','valid_for_comparison','halted']
    with (e.ROOT/'metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    sources=[{'title':'Binance public archives','url':'https://github.com/binance/binance-public-data','use':'逐文件校验的现货、永续成交价、标记价和资金费率'},
             {'title':'Binance futures liquidation protocols','url':'https://www.binance.com/en/support/faq/detail/360033525271','use':'真实强平依赖标记价及保证金；本研究未重建历史逐币档位，因此7%压力线触发后停止展示完整区间收益'},
             {'title':'Binance futures fees','url':'https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554','use':'交易费用、资金费用及强平费用不同；统一手续费为研究假设，非账户实际费率'}]
    e.base.dump(e.ROOT/'sources.json',sources)
    def num(x):return '不适用/风险中止' if x is None else f'{x:+.2f}%'
    lines=['四版本：排名缓冲、延迟重买与永续1至10倍比较','',headline,note,'',
           '固定主区间2025-01-01至2026-10-31，共669天；初始1000U；单边手续费0.1%、滑点0.05%；5分钟执行。永续额外计真实资金费率。',
           '每仓基准金额/保证金=min(200,2/20日波动率)。永续名义额=该保证金×杠杆；并非整个账户满仓1—10倍。',
           '共28现货对照+240永续固定场景。四版本分别独立比较；没有新增排名缓冲+延迟重买组合，没有改变60日/7日评分。',coverage_note,'']
    for venue in ('spot','perp'):
        lines.append('现货主区间' if venue=='spot' else '永续主区间（全部杠杆档位）')
        lines.append('版本 | 杠杆 | 年化 | 净收益 | 回撤 | 交易 | 全部历史门槛')
        for d in decisions:
            if d['venue']!=venue:continue
            r=d['main'];lines.append(f"{d['name']} | {d['leverage']} | {num(r['annualized_return_pct'])} | {num(r['return_pct'])} | {num(r['max_drawdown'])} | {r['trade_count']} | {'通过' if d['passes'] else '未通过'}")
        lines.append('')
    lines+=['改动效果（同市场、同杠杆、同成本，相对较慢选币基准）：']
    for d in decisions:
        if d['mode'] not in ('rank_buffer','delayed_retry') or d['delta_net_vs_slow'] is None:continue
        lines.append(f"{d['venue']} {d['leverage']}倍 {d['name']}：净利润差{d['delta_net_vs_slow']:+.2f}U，成本前差{d['delta_gross_vs_slow']:+.2f}U，费用/滑点/资金费差{d['delta_cost_vs_slow']:+.2f}U。")
    lines+=['','实施规则：',
            '排名缓冲：每周先保留当时实际持仓中位于合格排名前4的币，再从前2补空位；最多两币。未持有的第3/4名不会自动入选。',
            '延迟重买：亏损价格止损确认后，该币等至严格晚于确认时刻的下一周一，并至少冷却6小时；原全局止损暂停保持。',
            '现货与永续都使用同一份已完成日线选币；永续只在前一执行K线已有合约成交/标记价时允许新仓，没有对应合约的所选币留现金，不用其他币替补。',
            '资金费按档案的实际结算时间和间隔入账；既有仓位先结算后退出。边界新开仓保守支付正资金费、不领取负资金费。',
            '7%抵押品/标记名义额为沿用的保守压力线（5%维持保证金假设+2%储备），不是重建的交易所真实强平价格。逐5分钟标记低点检查，触及后中止并隐藏完整区间收益及年化。',
            '高低价同根内的先后顺序未知，强平压力检查先于普通日内止损，可能更保守。中止前曲线及原因仍可查阅。',
            '候选门槛：全部数据/资金费/保证金路径有效，主区间及跨年、费用、延迟场景收益均正且收盘回撤<=15%，主区间至少30笔。盘中同时最低价压力回撤另列。',
            '通过历史门槛不保证未来或真实盘中回撤≤15%；此前反复研究的历史不能视作全新样本外。未接账户、未改原模拟和既有前瞻观察。',
            '实现留痕：Pandas只读数组兼容修正发生于永续结果产生前；另明确区分“无合约成交历史”和“已有成交但缺标记价”，后者在开仓前按数据缺口中止，不作为未上市跳过。无策略参数变化，旧源码、指纹和第一批永续结果均保留。','',
            '网页：http://127.0.0.1:8765/rotation-lab']
    (e.ROOT/'四版本与永续杠杆比较报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'best':None if not best else {'mode':best['mode'],'venue':best['venue'],'leverage':best['leverage'],'cagr':best['main']['annualized_return_pct'],'dd':best['main']['max_drawdown']},'invalid':result['invalid'],'spot':[{'mode':d['mode'],'cagr':d['main']['annualized_return_pct'],'roi':d['main']['return_pct'],'dd':d['main']['max_drawdown'],'delta':d['delta_net_vs_slow']} for d in spot],'perp1':[{'mode':d['mode'],'cagr':d['main']['annualized_return_pct'],'roi':d['main']['return_pct'],'dd':d['main']['max_drawdown'],'issue':d['main']['data_issues'][:1]} for d in p1]}))

if __name__=='__main__':main()
