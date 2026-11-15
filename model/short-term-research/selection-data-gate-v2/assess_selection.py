"""Report every frozen scenario and explicitly retain invalid paths."""
import csv
import io
from collections import Counter
import availability_engine as e


def main():
    rows=e.base.read(e.ROOT/'metrics.json')
    index={(r['mode'],r['scenario']):r for r in rows}
    control=index['control_weekly__fixed1','main']
    primary=index['combined_hourly__fixed1','main']
    decisions=[]
    for mode in e.NAMES:
        whole=[index[mode,s] for s in ('main','double','triple','delay')]
        valid=all(r['valid_for_comparison'] for r in whole)
        passed=valid and all(r['return_pct']>0 and r['max_drawdown']<=15 for r in whole) and whole[0]['core_trades']>=30
        decisions.append(dict(mode=mode,complete_four=valid,historical_screen=passed,
            worst_dd=max(r['max_drawdown'] for r in whole) if valid else None,
            main_cagr_delta_vs_weekly=whole[0]['annualized_return_pct']-control['annualized_return_pct'] if whole[0]['valid_for_comparison'] else None))
    pairs=[]
    for scenario,*_ in e.SCENARIOS:
        for candidate,reference,kind in [
            ('control_hourly__fixed1','control_weekly__fixed1','cadence'),
            ('combined_hourly__fixed1','combined_weekly__fixed1','cadence'),
            *[(s+'_hourly__fixed1','control_hourly__fixed1','selector') for s in ('liquidity','continuity','residual','combined')],
            *[(s+'__tiered',s+'__fixed1','leverage') for s in e.SELECTORS]]:
            a,b=index[candidate,scenario],index[reference,scenario]
            valid=a['valid_for_comparison'] and b['valid_for_comparison']
            pairs.append(dict(candidate=candidate,reference=reference,scenario=scenario,kind=kind,valid=valid,
                net_delta_u=(a['return_pct']-b['return_pct'])*10 if valid else None,
                cagr_delta=a['annualized_return_pct']-b['annualized_return_pct'] if valid and a['annualized_return_pct'] is not None else None,
                fees_slippage_delta=a['fees']+a['slippage_cost']-b['fees']-b['slippage_cost'] if valid else None,
                gross_delta=a['gross_pnl']-b['gross_pnl'] if valid else None))
    diagnosis={}
    for mode in e.NAMES:
        for scenario,start,end,fee,delay in e.SCENARIOS[:3]:
            r=e.cached_run(start,end,mode,fee,delay)
            core=[t for t in r['trades'] if t['layer']=='core']
            exit_groups={reason:dict(count=sum(t['reason']==reason for t in core),
                net=sum(t['pnl'] for t in core if t['reason']==reason)) for reason in sorted({t['reason'] for t in core})}
            diagnosis[mode+'/'+scenario]=dict(valid=r['valid_for_comparison'],core_trades=len(core),
                median_hold_hours=float(e.np.median([t['hold_hours'] for t in core])) if core else None,
                average_hold_hours=float(e.np.mean([t['hold_hours'] for t in core])) if core else None,
                core_exit_groups=exit_groups,contributions=r['contributions'],
                selected_changes=sum(a['selected']!=b['selected'] for a,b in zip(r['selection_trace'],r['selection_trace'][1:])),
                coin_count=len({t['symbol'] for t in core}),boost_pnl=r['boost_pnl'],
                trade_notional=sum(t['qty']*(t['entry_price']+t['exit_price']) for t in r['trades']))
    decision=next(d for d in decisions if d['mode']=='combined_hourly__fixed1')
    improved=primary['valid_for_comparison'] and primary['annualized_return_pct']>control['annualized_return_pct']
    success=bool(decision['historical_screen'] and improved)
    headline='主要候选通过历史筛选，仍需前瞻验证' if success else '本轮未证明优化成功，保留原模拟策略'
    if not primary['valid_for_comparison']:
        explanation='小时组合版触发既有标记价缺口，481天完整收益无效。2025年与压力情景分别列示；已按新授权采用已知缺失隔离规则；不更换主要候选、不根据收益改截止日。'
    else:
        explanation='主要候选与原周度1×相比年化变化 '+f"{primary['annualized_return_pct']-control['annualized_return_pct']:+.2f}"+' 个百分点。是否通过以完整成本/延迟场景为准；历史通过不代表已经适合实盘。'
    result=dict(primary='combined_hourly__fixed1',headline=headline,explanation=explanation,
        primary_success=success,total=len(rows),valid=sum(r['valid_for_comparison'] for r in rows),
        decisions=decisions,pairs=pairs,diagnosis=diagnosis,history_seen=True,paper_changed=False,
        missing_paths=[dict(mode=r['mode'],scenario=r['scenario'],issues=r['data_issues']) for r in rows if not r['valid_for_comparison']])
    e.base.dump(e.ROOT/'assessment.json',result)
    columns=['mode','name','scenario','start','end','fee','delay_minutes','valid_for_comparison','annualized_return_pct','return_pct','max_drawdown','core_pnl','boost_pnl','core_trades','boost_trades','gross_pnl','fees','slippage_cost','funding_cost','mean_exposure_pct','intrabar_stress_dd','data_issues']
    b=io.StringIO();w=csv.DictWriter(b,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
    (e.ROOT/'metrics.csv').write_text('\ufeff'+b.getvalue(),encoding='utf-8')
    lines=['全池选币学术与公开方法优化研究（含每小时换币）',headline,explanation,'',
        '主要候选：四因子等权，每小时，1×。14版本×6场景=84；规则与数据先冻结，未重复调参。',
        '基础成本：1000U；单边手续费0.1%、滑点0.05%、实际永续资金费。压力费率0.2%/0.3%，额外延迟5分钟。',
        '小时资格池来自前一完整日，排名来自最近已完成小时柱；名次不变不强制换仓。30/60日跨度保持不变。',
        '完整构成与公式见protocol.json；来源见sources.json。现有模拟保持不变。','',
        '方案 | 场景 | 完整有效 | 年化% | 区间收益% | 最大回撤% | 底仓笔数 | 手续费+滑点U']
    for r in rows:
        vals=[r['annualized_return_pct'],r['return_pct'],r['max_drawdown']]
        lines.append(' | '.join([r['name'],r['scenario'],str(r['valid_for_comparison']),
            *[f'{v:.3f}' if v is not None else '无效/不足一年' for v in vals],str(r['core_trades']),f"{r['fees']+r['slippage_cost']:.3f}"]))
    lines+=['','配对差异（只有同一窗口均完整才比较）：',e.base.json.dumps(pairs,ensure_ascii=False,indent=2) if hasattr(e.base,'json') else str(pairs),
        '', '数据范围：复用上轮事先固定的2025-01-01至2026-04-26窗口；补充同区间的公开小时信号和新候选执行归档，所有版本使用同一数据清单。',
        '全池保留原做多规则；用户允许做空的BTC/ETH策略未被改动，本轮不新增未经研究的全池空头评分。',
        '独立样本外未完成；重复研究的历史不能重新命名为样本外。7%抵押品压力线不是交易所精确历史强平规则。',
        '网页：http://127.0.0.1:8765/selection-research']
    (e.ROOT/'研究结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(headline,'valid',result['valid'],'/',len(rows),flush=True)
    for r in rows:
        if r['scenario'] in ('main','2025') and r['variant']=='fixed1':
            print(r['mode'],r['scenario'],r['annualized_return_pct'],r['return_pct'],r['max_drawdown'],r['core_trades'],flush=True)


if __name__=='__main__':main()
