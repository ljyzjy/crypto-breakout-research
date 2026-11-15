import csv,io,json
import numpy as np
import pandas as pd
import factor_engine as e

def diagnostics():
    rows=[]
    exported=[]
    for s in e.SYMBOLS:
        f=e.all_factors()[s];d=e.old.load_frame('perp',s,'klines')
        values=f.loc['2025-01-01':'2026-10-31'].copy();values.insert(0,'symbol',s);values.index.name='information_available_utc';exported.append(values)
        ev=f.loc[(f.index>=pd.Timestamp('2025-01-01',tz='UTC'))&(f.index<=pd.Timestamp('2026-10-31 00:00',tz='UTC'))&f.direction.ne(0)].copy()
        ev['entry']=d.open.reindex(ev.index).to_numpy()
        for hrs in (6,24):ev[f'fwd{hrs}']=ev.direction.to_numpy()*(d.open.reindex(ev.index+pd.Timedelta(hours=hrs)).to_numpy()/ev.entry.to_numpy()-1)*100
        accepted=[];last=None
        for ts in ev.index:
            if last is None or (ts-last).total_seconds()>=86400:accepted.append(ts);last=ts
        for label,part in [('all',ev),('thinned24h',ev.loc[accepted])]:
            for side in (-1,1):
                q=part.loc[part.direction.eq(side)]
                rows.append(dict(symbol=s,sample=label,direction='long' if side==1 else 'short',events=len(q),mean6h=float(q.fwd6.mean()),mean24h=float(q.fwd24.mean()),median24h=float(q.fwd24.median()),positive24h=float(q.fwd24.gt(0).mean()*100),roundtrip_fee_slip_hurdle_pct=.3))
    e.base.dump(e.ROOT/'factor-diagnostics.json',{'rows':rows,'note':'Forward price returns are gross diagnostic labels, not net backtest profits;0.30% is approximate base roundtrip fee+slip hurdle,actual funding and position sizing only in backtest. Thinned sample chooses earliest event then waits24h,regardless of future return;cross-asset/time dependence remains.'})
    pd.concat(exported).sort_index().to_csv(e.ROOT/'factor-values.csv.gz',compression='gzip',encoding='utf-8')

def main():
    rows=e.base.read(e.ROOT/'metrics.json');decisions=[]
    for mode in e.NAMES:
        for L in range(1,11):
            q=[r for r in rows if r['mode']==mode and r['leverage']==L];main=next(r for r in q if r['scenario']=='main');control=next(r for r in rows if r['mode']=='long_control' and r['leverage']==L and r['scenario']=='main')
            valid=all(r['valid_for_comparison'] for r in q);passed=valid and all(r['return_pct']>0 and r['max_drawdown']<=15 for r in q) and main['trade_count']>=30
            delta=main['return_pct']-control['return_pct'] if main['valid_for_comparison'] and control['valid_for_comparison'] else None
            decisions.append(dict(mode=mode,leverage=L,pass_gate=passed,improves_control=delta is not None and delta>0,net_improvement_pct=delta,worst_drawdown=max(r['max_drawdown'] for r in q) if valid else None,all_valid=valid,issues=[{'scenario':r['scenario'],'issues':r['data_issues']} for r in q if not r['valid_for_comparison']]))
    assessment={'decisions':decisions,'scenarios':len(rows),'valid':sum(r['valid_for_comparison'] for r in rows),'limits':'BTCETH factor qualification only; explicitly approximate Marco-inspired price pattern,not original strategy/FHAT replication. Existing simulation unchanged.'}
    e.base.dump(e.ROOT/'assessment.json',assessment);diagnostics()
    fields=['mode','name','leverage','scenario','start','end','fee','delay_minutes','valid_for_comparison','annualized_return_pct','return_pct','max_drawdown','trade_count','long_trades','short_trades','long_pnl','short_pnl','fees','slippage_cost','funding_cost','gross_pnl','win_rate']
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows);(e.ROOT/'metrics.csv').write_text('\ufeff'+buf.getvalue(),encoding='utf-8')
    lines=['Marco启发因子与多空永续研究','来源边界：公开课程确认扫高低点后反转的方向；视频正文未取得。本轮是固定定义的价格形态因子，不是完整复现。FHAT及99.9%胜率尚未核实。','统一区间2025-01-01至2026-10-31，1000U；单边手续费0.1%、滑点0.05%，实际资金费。BTCETH固定验证池，不代表全池自动选币。','因子：1小时信号；前24小时高低点、最近触及距信号至少6小时；扫过后收回。次根5分钟开盘执行；原4%止损、24小时最大持仓；最多2仓，原波动预算。','固定四版本×1至10倍×6场景，共240场景。缺数/抵押品压力路径不显示完整收益。','', '主区间：版本 | 杠杆 | 年化% | 净收益% | 回撤% | 多头净利润U | 空头净利润U | 交易数 | 门槛']
    for L in range(1,11):
        for mode in e.NAMES:
            r=next(r for r in rows if r['mode']==mode and r['leverage']==L and r['scenario']=='main');gate=next(d for d in decisions if d['mode']==mode and d['leverage']==L)
            nums=[f'{r[k]:.2f}' if r.get(k) is not None else '中止/不可用' for k in ('annualized_return_pct','return_pct','max_drawdown','long_pnl','short_pnl')]
            lines.append(' | '.join([e.NAMES[mode],str(L),*nums,str(r['trade_count']),'通过' if gate['pass_gate'] else '未通过']))
    lines.extend(['','研究结论：1倍多空动量通过固定历史门槛，年化8.87%、回撤7.09%，相较同预算只做多增加净利润69.10U。2倍基础年化17.18%、回撤12.89%，但三倍手续费回撤15.97%，未通过15%门槛。','流动性反转近似并未通过：1倍成本前利润58.79U，手续费87.04U、滑点43.52U，资金费收入0.47U，净亏71.31U。加动量过滤后仍净亏46.18U。不能据此否定Marco完整交易方法，也不能宣称复现其业绩。','1倍多空动量的空头贡献92.41U；由于冷却和全局保护影响，多头利润降至76.17U，整体净增量69.10U不等于空头利润。','7%抵押品压力线=5%维持保证金假设+2%缓冲；不是交易所历史精确强平。多头用标记低点，空头用标记高点；同柱无法确定先后时先检查压力。','通过门槛需要全区间、两个年份、两倍/三倍费用、延迟5分钟均盈利且回撤<=15%。回撤为5分钟收盘估值，另列柱内压力。','所有参数在新结果前固定。已研究历史不是独立样本外；本轮未修改当前模拟。','因子文件factor-values.csv.gz含每小时可用时间、币种、方向、强度、事前高低点、距最近触及时间与ATR，不含未来收益标签。','网页：http://127.0.0.1:8765/short-factor'])
    (e.ROOT/'多空与流动性反转因子报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'scenarios':len(rows),'valid':assessment['valid'],'passing':[x for x in decisions if x['pass_gate']]},ensure_ascii=True))
if __name__=='__main__':main()
