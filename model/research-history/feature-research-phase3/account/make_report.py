"""Render the current audited-input account results; never reads superseded PnL."""
from pathlib import Path
import json
import pandas as pd

ROOT=Path(__file__).resolve().parent


def main():
    result=json.loads((ROOT/'account_results.json').read_text(encoding='utf-8'))
    rows=result['results'];baseline=rows[0]
    signal_count=len(pd.read_parquet(ROOT/'event-signals.parquet'))
    trades=pd.DataFrame(json.loads((ROOT/'results/event_baseline/main-trades.json').read_text(encoding='utf-8')))
    exit_counts=trades.groupby('reason').size().to_dict() if len(trades) else {}
    side_pnl=trades.groupby('side').agg(trades=('net','size'),gross=('gross','sum'),net=('net','sum')).to_dict('index') if len(trades) else {}
    diagnostics={'signal_candidates':signal_count,'main_exit_counts':exit_counts,'main_side_pnl':side_pnl,
        'main_first_entry_utc':str(pd.Timestamp(trades.entry_ts.min(),unit='ms',tz='UTC')) if len(trades) else None,
        'main_last_exit_utc':str(pd.Timestamp(trades.exit_ts.max(),unit='ms',tz='UTC')) if len(trades) else None}
    (ROOT/'account_diagnostics.json').write_text(json.dumps(diagnostics,indent=2),encoding='utf-8')
    lines=['# Phase 3 最终账户回放结果','',
        f'六组特征的主检验均未通过预先规定的多重检验门槛，因此没有增强候选进入账户回测。按冻结协议，运行共同成熟事件基准的五种成本场景。无选中模型时，匹配基准与无模型输入限制基准拥有完全相同的 {signal_count:,} 个候选机会；结果记录为同一结果的别名。', '',
        '评估期为 2025-07-01 至 2026-04-26，共 300 天，初始权益 1,000 USDT，总入场名义上限 1×。未报告年化收益。', '',
        '| 场景 | 净收益 | 收盘最大回撤 | 分钟内 mark 压力回撤 | 笔数 | 利润因子 | 永久暂停 UTC |',
        '|---|---:|---:|---:|---:|---:|---|']
    for x in rows:
        pause=str(pd.Timestamp(x['permanent_pause_ts'],unit='ms',tz='UTC')) if x['permanent_pause_ts'] else '未暂停'
        pf=f"{x['profit_factor']:.3f}" if x['profit_factor'] is not None else 'NA'
        lines.append(f"| {x['scenario']} | {x['return_pct']:.4f}% | {x['max_drawdown']:.4f}% | {x['intrabar_stress_dd']:.4f}% | {x['trades']} | {pf} | {pause} |")
    lines += ['', '各路径保留原 8% 峰值回撤永久暂停；较小的最终回撤包含长期停机的影响，不能据此声称连续运营已经控制回撤。', '',
        '| 场景 | 毛收益 U | 手续费 U | 滑点 U | 资金费净支出 U | 净收益 U | 有交易日数 | 全日现金日数 | 停机等价日 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for x in rows:
        lines.append(f"| {x['scenario']} | {x['gross_pnl']:.4f} | {x['fees']:.4f} | {x['slippage_cost']:.4f} | {x['funding_cost']:.4f} | {x['net_pnl']:.4f} | {x['active_calendar_days']} | {x['fully_cash_calendar_days']} | {x['halted_days']:.3f} |")
    lines += ['', '资金费负数表示净收入。', '',
        f"主场景原始价格毛收益 {baseline['gross_pnl']:.2f} U，手续费与滑点合计 {baseline['fees']+baseline['slippage_cost']:.2f} U，扣费后净收益 {baseline['net_pnl']:.2f} U。",
        f"300 个日历日中有 {baseline['active_calendar_days']} 日发生交易，{baseline['fully_cash_calendar_days']} 日整日现金；持仓分钟累计等价 {baseline['active_days_equivalent']:.3f} 天，永久暂停累计等价 {baseline['halted_days']:.3f} 天。", '',
        '退出原因笔数：'+', '.join(f'{k}: {v}' for k,v in exit_counts.items())+'。',
        '方向归因：'+', '.join(f"{k} {v['trades']} 笔、净收益 {v['net']:.2f} U" for k,v in side_pnl.items())+'。仅作诊断，没有据此删除方向或重调阈值。', '',
        '已统一修复并留痕：开盘退出前审计资金费覆盖；压力权益包含当分钟实际资金费；EMA仅用Phase 2原509档；按symbol文件读取所有60个映射资产且校验内部contract，恢复PEPE/BONK/SHIB的1000单位合约；已知隔离先从小时排名候选集合剔除。隔离严格按已知时间，不回溯删除此前排名。旧两轮结果位于superseded目录并标记不可作最终比较，所有五种成本在相同最终输入下重跑。', '',
        '事件特征在初始突破后五根分钟线完成才使用，入场再延迟一分钟。没有用未来标签有效性过滤候选；没有更改策略门槛或按收益调整参数。touch_ts为沿用旧输出格式的结构窗口起点，并不代表确认了传统回踩形态。', '',
        '0.05%/边费率仍是共同研究假设，并非用户账户实际历史费率核验；固定滑点是估计，不含盘口、历史精确下单过滤器或逐档保证金与强平重建。当前模拟、网站和旧研究未写入。', '',
        '完整指标：account_results.json；日历权益：daily_accounts.csv；币种方向归因：coin_attribution.csv；逐分钟权益、交易、入场审计和逐项资金费：results/event_baseline/。']
    (ROOT/'账户回放说明.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'report_written':True,**diagnostics}))


if __name__=='__main__':main()
