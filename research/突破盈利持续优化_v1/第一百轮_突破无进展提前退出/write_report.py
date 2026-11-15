"""Write a paired time-stop report after independent path and wallet audits."""
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def f(x,d=4):return '—' if x is None else f'{x:.{d}f}'


def main():
    result=json.loads((H/'进展退出结果汇总.json').read_text(encoding='utf-8'));audit=json.loads((H/'进展退出汇总独立核验.json').read_text(encoding='utf-8'))
    wallet=json.loads((H/'共享钱包情景汇总.json').read_text(encoding='utf-8'));wa=json.loads((H/'共享钱包独立核验.json').read_text(encoding='utf-8'))
    paths=json.loads((H/'进展退出独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256']==bulk.sha(H/'进展退出结果汇总.json')
    assert wa['all_checks_pass'] and wa['result_sha256']==bulk.sha(H/'共享钱包情景汇总.json') and paths['all_checks_pass']
    lines=['# 30 秒无进展提前退出：2022 原始逐笔配对','',
           '同一入场、止损、2R 目标和市价成本下，入场至少 30 秒后读取第一笔原始成交；如果顺向进展不足 0.25R，且原退出信号尚未发生，则发出退出信号，至少 5 秒后模拟市价退出。否则沿用原退出。费用及滑点每边各 0.05%，资金费随新持有区间重算。',
           '', '| 杠杆 | 可配对交易 | 原退出净盈利／净胜率 | 原退出平均名义净收益 | 新退出净盈利／净胜率 | 新退出平均名义净收益 | 新退出利润因子 | 额外未知 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for lev in (10,20):
        a=next(x for x in result['rows'] if x['leverage']==lev and x['cohort']=='baseline_paired' and x['exit_slippage_pct']==.05)
        b=next(x for x in result['rows'] if x['leverage']==lev and x['cohort']=='time_stop' and x['exit_slippage_pct']==.05)
        z=next(x for x in result['rows'] if x['leverage']==lev and x['cohort']=='pair_changes')
        lines.append(f"| {lev}× | {a['trades']} | {a['net_wins']}／{f(a['net_win_rate_pct'],2)}% | {f(a['mean_net_pct_notional'])}% | {b['net_wins']}／{f(b['net_win_rate_pct'],2)}% | {f(b['mean_net_pct_notional'])}% | {f(b['profit_factor'],3)} | {z['extra_unknown_paths']} |")
    lines+=['','逐笔配对变化：','']
    for lev in (10,20):
        z=next(x for x in result['rows'] if x['leverage']==lev and x['cohort']=='pair_changes')
        lines.append(f"- {lev}×：{z['early_exit_paths']} 笔触发提前退出；净收益改善 {z['better']} 笔、变差 {z['worse']} 笔、未变 {z['unchanged']} 笔。")
    lines+=['','同一已知路径、1,000 U 起始、单笔计划风险 0.5%、组合计划风险 1% 的共享钱包情景：','']
    for lev in (10,20):
        a=next(x for x in wallet['rows'] if x['leverage']==lev and x['period']=='baseline_paired' and not x['reverse_ties'])
        b=next(x for x in wallet['rows'] if x['leverage']==lev and x['period']=='time_stop' and not x['reverse_ties'])
        lines.append(f"- {lev}×：原退出 {f(a['final_wallet'],2)} U／已实现钱包余额回撤 {f(a['realized_wallet_drawdown_pct'],2)}%；新退出 {f(b['final_wallet'],2)} U／{f(b['realized_wallet_drawdown_pct'],2)}%。")
    lines+=['','这里的收益分母为入场名义本金。钱包排除未知机会，回撤不含浮动权益，不能认定完整账户最大回撤；计划风险也不能保证实际亏损上限。原排名口径还有 240 个未知小时。',
            '',f"已对 {paths['paths_checked']} 条路径用不同解析器和标量逻辑复核触发与退出，并复算 {paths['risk_settlements_checked']} 条风险结算。该年及参数构思涉及已研究历史，不是独立未来样本；历史成交价加固定滑点仅为市价代理。", 
            '', '[固定方案](研究方案.md) · [配对明细](进展退出配对明细.csv) · [路径独立核验](进展退出独立核验.json) · [钱包独立核验](共享钱包独立核验.json)']
    (H/'无进展提前退出结果.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('EXT100_REPORT',flush=True)


if __name__=='__main__':main()
