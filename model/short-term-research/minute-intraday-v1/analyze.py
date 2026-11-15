"""Publish all predeclared scenarios, including negative or invalid outcomes."""
from pathlib import Path
import numpy as np
import pandas as pd
from prepare_data import ROOT,read,dump,sha

def slices(curve):
    x=curve.copy();x['date']=pd.to_datetime(x.ts-1,unit='ms',utc=True)
    result=[];previous=1000.
    for month,g in x.groupby(x.date.dt.strftime('%Y-%m'),sort=True):
        final=float(g.equity.iloc[-1]);peak=np.maximum.accumulate(np.r_[previous,g.equity.to_numpy()])[1:]
        result.append({'month':month,'start_equity':previous,'end_equity':final,
            'return_pct':100*(final/previous-1),'max_drawdown':float(np.max(100*(1-g.equity.to_numpy()/peak)))})
        previous=final
    return result

def main():
    rows=read(ROOT/'metrics.json');m=next(x for x in rows if x['scenario']=='main')
    curve=pd.read_parquet(ROOT/'results/main-curve.parquet');t=pd.DataFrame(read(ROOT/'results/main-trades.json'))
    def by(col):
        if t.empty:return []
        return [{col:str(k),'trades':len(g),'net':float(g.net.sum()),'gross':float(g.gross.sum()),
                 'fees':float(g.fees.sum()),'slippage':float(g.slippage.sum()),'funding':float(g.funding.sum())}
                for k,g in t.groupby(col)]
    passed=all(r['valid_for_comparison'] and r['return_pct']>0 and r['max_drawdown']<=15 for r in rows) and m['trades']>=100
    monthly=slices(curve)
    assessment={'primary':'minute_intraday_v1','passed':passed,'all_paths_valid':all(r['valid_for_comparison'] for r in rows),
       'scenarios':len(rows),'threshold_max_drawdown':15,'history_seen':True,'paper_changed':False,
       'headline':'通过本轮历史筛选，尚需前瞻验证' if passed else '未通过历史筛选，保留规则与失败结果',
       'main':m,'monthly':monthly,'by_symbol':sorted(by('symbol'),key=lambda r:r['net'],reverse=True),
       'by_side':by('side'),'by_exit':by('reason'),'gross_less_cost':m['gross_pnl']-m['fees']-m['slippage_cost']-m['funding_cost'],
       'positive_months':sum(r['return_pct']>0 for r in monthly),'months':len(monthly),
       'active_trading_days':int(pd.to_datetime(t.entry_ts,unit='ms',utc=True).dt.tz_convert('Asia/Shanghai').dt.date.nunique()) if len(t) else 0,
       'limitations':['一分钟OHLC无法还原秒级成交顺序；双触发先计止损。',
          '固定滑点是研究假设；资金费率按历史结算，结算标记价以所在分钟开盘近似。',
          '当前费率基准统一应用历史；未还原历年账户等级、折扣、数量步长和最小订单门槛变更，最低订单暂设10USDT。',
          '该历史已被研究；分月表现不是全新样本外证据。',
          '8%回撤暂停会保留后续现金期；页面披露暂停日期，历史15%以内不保证未来。',
          '秒级公共数据观察独立于本次回测，不代表已验证秒级盈利或实际订单延迟。']}
    dump(ROOT/'assessment.json',assessment)
    pd.DataFrame(rows).drop(columns=['rejection_counts','issues']).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
    t.to_csv(ROOT/'trades.csv',index=False,encoding='utf-8-sig')
    lines=['分钟突破 · 全池多空 · 第一版研究结果',assessment['headline'],'',
       '区间：2025-01-01—2026-04-26（UTC）；初始1000USDT；固定规则，仅此一个策略。',
       '仓位上限1×；5×仅保留为后续研究上限，本轮未启用。现有DailyMomentum模拟不变。',
       '一分钟入场，十五分钟方向与ATR，每小时全池排名，最多2仓，最长60分钟；卖出后补位。',
       '基础单边手续费0.05%+估计滑点0.05%，历史资金费率另计。','']
    for r in rows:
        annual=f"{r['annualized_return_pct']:.2f}%" if r.get('annualized_return_pct') is not None else '不年化'
        lines.append(f"{r['scenario']}: 净年化{annual}，净收益{r['return_pct']:.2f}%，最大回撤{r['max_drawdown']:.2f}%，{r['trades']}笔，数据有效={r['valid_for_comparison']}")
    lines.extend(['',f"主场景毛收益{m['gross_pnl']:.4f}U，手续费{m['fees']:.4f}U，滑点{m['slippage_cost']:.4f}U，资金费率成本{m['funding_cost']:.4f}U，净收益{m['net_pnl']:.4f}U。",
        f"单笔净收益{m['average_trade_net']:.4f}U，胜率{m['win_rate']:.2f}%，平均持有{m['mean_holding_minutes']:.2f}分钟。",
        f"账户暂停时间：{pd.Timestamp(m['permanent_pause_ts'],unit='ms',tz='UTC').isoformat() if m['permanent_pause_ts'] else '未触发'}。",
        '',*assessment['limitations']])
    (ROOT/'研究结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(assessment['headline'],flush=True)

if __name__=='__main__':main()
