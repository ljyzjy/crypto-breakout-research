"""Create a concise evidence-bounded report from independently checked results."""
import json
from pathlib import Path
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent;R93=H.parent/'第九十三轮_原始逐笔抽样交叉核验'


def fmt(x,d=4):return '—' if x is None else f'{x:.{d}f}'


def main():
    report=json.loads((H/'原始逐笔汇总.json').read_text(encoding='utf-8'));audit=json.loads((H/'原始逐笔汇总独立核验.json').read_text(encoding='utf-8'))
    wallet=json.loads((H/'共享钱包情景汇总.json').read_text(encoding='utf-8'));wa=json.loads((H/'共享钱包独立核验.json').read_text(encoding='utf-8'))
    tape=json.loads((H/'原始逐笔独立抽样核验.json').read_text(encoding='utf-8'));risk=json.loads((H/'风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256']==bulk.sha(H/'原始逐笔汇总.json')
    assert wa['all_checks_pass'] and wa['result_sha256']==bulk.sha(H/'共享钱包情景汇总.json')
    assert tape['all_checks_pass'] and risk['all_checks_pass']
    old=json.loads((R93/'原始数据分歧敏感性.json').read_text(encoding='utf-8'))['rows']
    lines=['# 2022 年原始逐笔一秒观察回测','',
           '首次触价后观察一秒，满足方向与笔数门槛后再至少等待一秒，以随后的原始成交价加不利滑点模拟市价入场；退出信号后至少等待五秒。每边假设手续费及不利滑点各 0.05%，资金费另计。',
           '', '| 杠杆 | 已知交易 | 净盈利数 | 净胜率 | 平均每笔名义净收益 | 利润因子 | 活跃 UTC 日 | 已列候选未知 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for lev in (10,20):
        r=next(x for x in report['rows'] if x['leverage']==lev and x['exit_slippage_pct']==.05)
        lines.append(f"| {lev}× | {r['trades']} | {r['net_wins']} | {fmt(r['net_win_rate_pct'],2)}% | {fmt(r['mean_net_pct_notional'])}% | {fmt(r['profit_factor'],3)} | {r['active_utc_days']} | {r['unknown_candidates']} |")
    lines+=['','固定入退信号及入场价格，将退出滑点从 0.05% 增至 0.075%／0.10% 的静态压力：','']
    for lev in (10,20):
        vals=[next(x for x in report['rows'] if x['leverage']==lev and x['exit_slippage_pct']==slip)['mean_net_pct_notional'] for slip in (.05,.075,.1)]
        lines.append(f"- {lev}×：平均名义净收益依次为 {'／'.join(fmt(x)+'%' for x in vals)}。")
    lines+=['','已知路径共享钱包情景以 1,000 U 起始、信号时单笔计划风险 0.5%、待入场及持仓合计计划风险 1% 计量；仅模拟可核验机会：','']
    for lev in (10,20):
        w=next(x for x in wallet['rows'] if x['leverage']==lev and not x['reverse_ties'])
        lines.append(f"- {lev}×：模拟成交 {w['simulated_trades']} 笔，钱包 {fmt(w['initial_wallet'],2)} → {fmt(w['final_wallet'],2)} U；已实现钱包余额回撤 {fmt(w['realized_wallet_drawdown_pct'],2)}%。")
    lines+=['','上述回撤不含持仓浮盈亏，不能作为账户最大回撤；模型计划风险也不是每笔实际亏损上限。未知候选未进入钱包，排名未知小时不在候选集内。',
            '', '## 与原聚合成交口径的关系','']
    for lev in (10,20):
        r=next(x for x in old if x['holding_rule']=='original' and x['cohort']=='base' and x['leverage']==lev and x['exit_slippage_pct']==.05)
        lines.append(f"- 原聚合口径、抽样分歧保守列未知：{lev}× {r['trades']} 笔／{r['net_wins']} 笔净盈利，平均名义净 {fmt(r['mean_net_pct_notional'])}%，已列候选未知 {r['sensitivity_unknown']}。")
    lines+=['','本轮“首秒至少三条”按原始成交记录计数，旧口径按聚合成交记录计数，两个阈值的含义不同；入退参考价也可能变化。不能把差异归因于单一因素，更不能把新口径当作真实成交。',
            '',f"原始日档完成 284／284 组，事前固定的 {tape['sample_count']} 个候选经过另一解析器及标量时序复放；{risk['verified_source_archives_redownloaded']} 份风险来源重新下载并核对，{risk['risk_paths_independently_checked']} 条路径独立复算。历史币种是事后确定的固定 11 币，存在幸存者偏差。", 
            '', '原排名口径还有 240 个未知小时；零成交替代口径可恢复 196 小时且无新增候选，仍有 44 小时未知。以上均是已研究历史，不是独立未来验证。固定滑点为假设，真实市价成交与交易所强平未被证明。',
            '', '[官方公共数据说明](https://github.com/binance/binance-public-data/) · [逐笔汇总](原始逐笔汇总.json) · [摘要独立核验](原始逐笔汇总独立核验.json) · [钱包独立核验](共享钱包独立核验.json)']
    (H/'原始逐笔完整结果.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('EXT98_REPORT',flush=True)


if __name__=='__main__':main()
