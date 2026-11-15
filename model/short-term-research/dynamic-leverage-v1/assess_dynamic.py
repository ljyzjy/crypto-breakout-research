import csv,io,json
from collections import Counter
import dynamic_engine as e

def main():
    rows=e.base.read(e.ROOT/'metrics.json');decisions=[]
    control=next(r for r in rows if r['mode']=='fixed1' and r['scenario']=='main')
    for mode in e.NAMES:
        q=[r for r in rows if r['mode']==mode];main=next(r for r in q if r['scenario']=='main');valid=all(r['valid_for_comparison'] for r in q)
        gate=valid and all(r['return_pct']>0 and r['max_drawdown']<=15 for r in q) and main['core_trades']>=30
        decisions.append(dict(mode=mode,name=e.NAMES[mode],passes_risk_profit=gate,improves_1x=main['valid_for_comparison'] and main['return_pct']>control['return_pct'],worst_dd=max(r['max_drawdown'] for r in q) if valid else None,all_valid=valid,delta_net_u=(main['return_pct']-control['return_pct'])*10 if main['valid_for_comparison'] else None))
    detail={}
    for mode in ('vol_only','tiered'):
        r=e.cached_run('2025-01-01','2026-10-31',mode);a=r['leverage_audit'];adds=[x for x in r['adjustments'] if x['action']=='add'];core=[t for t in r['trades'] if t['layer']=='core'];boost=[t for t in r['trades'] if t['layer']!='core']
        detail[mode]=dict(actual_multiplier_counts=dict(Counter(str(x['actual']) for x in a)),regime_ceiling_counts=dict(Counter(str(x['target']) for x in a)),max_actual_multiplier=max((x['actual'] for x in a),default=1),add_fill_count=len(adds),distinct_add_decisions=len({(x['ts'],x['symbol']) for x in adds}),reduce_reasons=dict(Counter(x['reason'] for x in r['adjustments'] if x['action']=='reduce')),boost_gross=sum(t['gross_pnl'] for t in boost),boost_fees=sum(t['fees'] for t in boost),boost_slippage=sum(t['slippage'] for t in boost),boost_funding=sum(t['funding'] for t in boost),boost_net=sum(t['pnl'] for t in boost),core_net=sum(t['pnl'] for t in core),core_net_difference=sum(t['pnl'] for t in core)-control['core_pnl'])
        fields=['ts','information_ts','symbol','side','target','actual','account_dd','core_net_unrealized','planned_stop_risk_pct','reasons','features'];buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for x in a:w.writerow({**x,'reasons':'；'.join(x['reasons']),'features':json.dumps(x['features'],ensure_ascii=False)})
        (e.ROOT/(mode+'-decision-audit.csv')).write_text('\ufeff'+buf.getvalue(),encoding='utf-8')
    primary=next(d for d in decisions if d['mode']=='tiered');adopt=primary['passes_risk_profit'] and primary['improves_1x']
    assessment=dict(decisions=decisions,details=detail,primary='tiered',primary_passed=adopt,headline='上限5倍的条件杠杆通过本轮历史筛选，仍需前瞻验证' if adopt else '上限5倍的条件杠杆未同时满足收益提升与风险门槛',scenarios=30,valid=sum(r['valid_for_comparison'] for r in rows),paper_changed=False,history_seen=True)
    e.base.dump(e.ROOT/'assessment.json',assessment)
    fields=['mode','name','scenario','start','end','fee','delay_minutes','valid_for_comparison','annualized_return_pct','return_pct','max_drawdown','core_pnl','boost_pnl','core_trades','boost_trades','fees','slippage_cost','funding_cost','mean_exposure_pct','boost_held_time_pct']
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows);(e.ROOT/'metrics.csv').write_text('\ufeff'+buf.getvalue(),encoding='utf-8')
    lines=['动态杠杆研究：1倍为基础，上限5倍',assessment['headline'],'','规则在新结果前固定；BTCETH永续，2025-01-01至2026-10-31，初始1000U。单边手续费0.1%、滑点0.05%，实际资金费。','每天读取前一完整UTC日：20日波动<=过去120期中位数，5日波动<=20日波动时，允许1.5倍。10/30/60日动量同向、上一日未出现2倍日波动冲击、已知24小时付费率<=0.03%时，上限提高到5倍。','实际加仓还要求底仓持有至少24小时并净浮盈、账户回撤<5%、冷却/保护已结束、预计组合到止损损失(含退出成本)<=净值2%。按0.5份底仓逐档增加，BTC先于ETH，不强行加满5倍。','波动/确认条件下降时减额外仓；账户已知回撤>=8%时，下根5分钟开盘撤额外仓，底仓保留。额外仓独立4%止损，底仓退出时一并退出；减仓后额外仓冷却24小时。','1至5倍指相对原底仓的数量倍数；行情漂移时实际名义/保证金不同。额外仓共享对应币种原保证金；所有加减仓均付费，不自动补保证金。','', '主区间：版本 | 年化% | 净收益% | 回撤% | 额外仓净利润U | 压力最差回撤%']
    for d in decisions:
        r=next(r for r in rows if r['mode']==d['mode'] and r['scenario']=='main');vals=[r['annualized_return_pct'],r['return_pct'],r['max_drawdown'],r['boost_pnl'],d['worst_dd']];lines.append(' | '.join([r['name'],*[f'{v:.2f}' if v is not None else '路径无效' for v in vals]]))
    lines.extend(['','条件杠杆明细：',json.dumps(detail,ensure_ascii=False,indent=2),'','7%抵押品压力线沿用既有研究假设，不是交易所历史精确强平。持仓缺数/触线即中止，隐藏完整收益。','历史已被研究，不是独立样本外；风险预算/8%降杠杆触发均不能保证未来最大回撤<=15%。当前模拟与前瞻观察未改。','网页：http://127.0.0.1:8765/dynamic-leverage'])
    (e.ROOT/'动态杠杆上限5倍研究报告.txt').write_text('\n'.join(lines),encoding='utf-8');print(json.dumps(assessment,ensure_ascii=True))
if __name__=='__main__':main()
