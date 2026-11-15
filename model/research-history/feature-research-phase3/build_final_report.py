"""Summarize frozen results; never fits, selects or changes a trading rule."""
from pathlib import Path
from datetime import datetime,timezone
import json,sys
P=Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def dump(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
inc=read(P/'incremental/incremental_results.json')
acc=read(P/'account/account_results.json')
audit=read(P/'audit/audit_summary.json')
assert audit['implementation_audit_passed_with_scope_limits'] and not audit['unresolved_implementation_findings_in_audited_scope']
assert inc['selected_groups']==acc['selected_groups']==[]
assert len(acc['results'])==5 and all(r['elapsed_days']==300 for r in acc['results'])
assert all(r['return_pct']<0 for r in acc['results']), 'Rewrite the narrative from the actual final results before publication'
names={'F1':'自身6h动量、BTC残差动量','F2':'路径效率、涨跌集中度','F3':'相对实现波动、分钟幅度/ATR','F4':'突破边界距离、外侧接受比例','F5':'回撤深度、修复比例','F6':'成交额RVOL、成交笔数RVOL'}
scenarios={'main':'主成本','fee2':'手续费×2','fee3':'手续费×3','slip2':'滑点×2','delay1':'额外延迟1分钟'}
main=next(r for r in acc['results'] if r['scenario']=='main')
signal_count=main['signal_candidates']
pause=datetime.fromtimestamp(main['permanent_pause_ts']/1000,timezone.utc).isoformat()
feature_rows=[{'group':r['group'],'features':names[r['group']],'relative_prediction_loss_improvement_pct':100*r['relative_loss_improvement'],'raw_p':r['p_raw'],'holm6_p':r['p_holm6'],'selected':r['selected'],'screen_rows':r['screen']['paired']['records']} for r in inc['groups']]
scenario_rows=[{'scenario':scenarios[r['scenario']],'net_return_pct':r['return_pct'],'max_drawdown_pct':r['max_drawdown'],'intrabar_stress_drawdown_pct':r['intrabar_stress_dd'],'trades':r['trades'],'profit_factor':r['profit_factor'],'valid':r['valid_for_comparison'],'passed_performance_gate':r['candidate_success_screen'],'active_calendar_days':r['active_calendar_days'],'fully_cash_calendar_days':r['fully_cash_calendar_days'],'permanent_pause_utc':datetime.fromtimestamp(r['permanent_pause_ts']/1000,timezone.utc).isoformat() if r['permanent_pause_ts'] else None} for r in acc['results']]
result={'completed_utc':datetime.now(timezone.utc).isoformat(),'conclusion':'No feature group passed the frozen incremental gate; no enhanced strategy was manufactured. All five baseline cost scenarios lose money. No successful strategy demonstrated.','feature_groups':feature_rows,'account_comparison':scenario_rows,'main_cost_attribution':{k:main[k] for k in ['gross_pnl','fees','slippage_cost','funding_cost','net_pnl','final_equity']},'account_evaluation_days':300,'cagr_evaluated':False,'enhanced_candidates_run':0,'leverage_cap':1,'paper_changed':False,'chronological_historical_only':True,'audit':audit}
dump(P/'phase3_results.json',result)
lines=['# 十二项特征增量检验与同成本账户回测结果','',
'本轮完成了特征增量检验、共同事件基准的五种成本回放及独立审计。结论：六组特征均未通过冻结的入选门槛；没有新增增强候选，五种成本下基准均亏损。本轮没有达到“提高净收益、最大回撤不超过15%”的成功标准，现有模拟未修改。','',
'## 研究设计与可解释边界','',
'固定历史为2025-01-01至2026-04-26，共481天；2025年1—3月训练、4—6月筛选、2025-07-01至2026-04-26共300天做账户评价。数据来自此前统一的历史日池和60个映射永续合约，不是用今天存续币列表回填过去。此历史曾被研究过，因此只能称历史顺序验证，不能称完全未见样本外验证。','',
'先冻结规则再读取新标签：30分钟为主检验，15/60分钟仅描述；65分钟边界隔离；训练段单独决定尺度、币固定效应和OLS系数；每组基准/增强使用同一批观测；按币日等权计算损失，以7日时间块、2000次固定种子重抽样，Holm校正六组检验。十二项特征中自身6小时动量和成交额RVOL已在控制项，新增检验为十项变量、六组假设。','',
'## 十二项特征的结果','',
'预测误差改善为正表示误差下降，负数表示误差略增；这不是交易收益率。F3预测未来最大不利波动（MAE），其他组预测方向收益。','',
'| 组别与构成 | 误差改善 | 原始p | 校正后p | 筛选观测 | 入选 |','|---|---:|---:|---:|---:|---|']
for r in feature_rows:
    lines.append(f"| {r['group']} {r['features']} | {r['relative_prediction_loss_improvement_pct']:+.5f}% | {r['raw_p']:.6f} | {r['holm6_p']:.6f} | {r['screen_rows']:,} | 否 |")
lines += ['',
'F3是唯一出现误差改善的组，改善1.09405%，但校正后p=0.155922，高于预定0.05门槛。因此保留为尚未证实的风险线索，不将它改写成已证实的收益信号，也不例外加仓或减仓。F1等五组未显示本轮固定线性规格的增量价值；这不能推出它们在所有非线性关系、交易条件和样本中永远无效。','',
'F1训练只有46个有效日、9个有效周、31币、40,474条观测，原因是此前已发现的连续配对历史窗口失效；其他组训练覆盖90天。筛选段各组均覆盖91天。80%覆盖门槛沿用第二阶段全期数据质量门槛，未事后增加或放松分段门槛；缺失未补值。','',
'## 为什么没有“增强策略收益表”','',
f'冻结方案只允许通过校正后门槛的特征进入联合alpha、F3减半风险或两者组合。本轮入选为空，因此没有拟合这些账户模型、没有用弱证据拼出候选。匹配基准与未限制基准在本轮使用完全相同的{signal_count:,}个已知时点机会，结果为同一回放的别名，没有重复计算伪造不同策略。','',
'共同基准仍保留历史日池、小时RVOL≥1.5、方向排名前三、已收盘15分钟EMA20方向/斜率、结构止损、2R目标、最多持有60分钟以及原组合风控。为了让突破后特征可知，决策统一等初始突破及其后5根分钟线完成，再延迟1分钟入场。它改变了旧uncapped策略的入场定义，不能把本轮与旧报告不同区间的收益直接相减归因于特征。','',
'## 同数据、同成本账户回放','',
'起始资金1000 USDT，1×总入场名义上限。各成本情景都独立重算仓位和账本；持仓时的历史资金费另计。回放包含完整300个日历日，不删除永久停机后的现金期。','',
'| 成本场景 | 净收益 | 收盘最大回撤 | 分钟内压力回撤 | 平仓笔数 | 净利润因子 |','|---|---:|---:|---:|---:|---:|']
for r in scenario_rows:
    lines.append(f"| {r['scenario']} | {r['net_return_pct']:+.4f}% | {r['max_drawdown_pct']:.4f}% | {r['intrabar_stress_drawdown_pct']:.4f}% | {r['trades']} | {r['profit_factor']:.4f} |")
lines += ['',
f"主成本终值{main['final_equity']:.4f} USDT，净亏{abs(main['net_pnl']):.4f} USDT；胜率{main['win_rate']:.2f}%，平均持有{main['mean_holding_minutes']:.2f}分钟。主场景在{pause}触发原8%永久暂停，300天仅{main['active_calendar_days']}天曾有持仓，{main['fully_cash_calendar_days']}个完整自然日全程空仓。回撤约8%包含停机机制的作用，不代表策略持续交易300天后仍能将回撤控制在15%。",'',
'| 主成本损益拆解 | USDT |','|---|---:|',
f"| 原始价格毛损益 | {main['gross_pnl']:+.4f} |",f"| 手续费 | −{main['fees']:.4f} |",f"| 滑点损耗 | −{main['slippage_cost']:.4f} |",f"| 资金费净支出 | −{main['funding_cost']:.4f} |",f"| 最终净损益 | {main['net_pnl']:+.4f} |",'',
'账本显示这套共同事件基准的毛收益不足以覆盖交易成本；不能靠增加杠杆把负净优势变成正优势。本轮固定为1×，未重新启用5×动态杠杆。由于独立账户评价只有300天，按原登记规则不报告年化收益，避免用公式外推冒充已验证年化。','',
'固定持有机会的筛选期描述同样显示成本压力：时钟样本30分钟平均方向毛变动约+0.562bp，事件样本约−0.876bp，均远小于主场景固定20bp往返成本代理。它们是重叠机会的描述统计，不是实际可同时执行的账户收益；MAE/MFE也是事后路径统计，不能把最佳波幅当作可实现利润。','',
'## 成本的真实性与限制','',
'本轮为保持同成本比较，沿用每边0.05%手续费和0.05%滑点，往返约0.20%（20bp），并使用历史资金费时间戳与费率。手续费×2/×3、滑点×2、额外延迟1分钟均按登记执行。0.05%是研究假设/公开示例，并未验证用户账户VIP折扣和逐历史日期费率；滑点也是估计，没有历史订单簿成交回放。因此这是统一的成本压力检验，不能称为用户账户逐笔真实成交复制。',
'[币安手续费说明](https://www.binance.com/en/support/faq/detail/360033544231)说明费率与VIP等级等有关；[资金费说明](https://www.binance.com/en/support/faq/detail/360033525031)给出按标记价格名义金额计算资金费的口径。历史文件与校验机制参见[币安公开数据仓库](https://github.com/binance/binance-public-data)。','',
'## 审计、修复和原模拟保护','',
'独立审计重建六组匹配ID、训练尺度与系数、币日损失、块重抽样和多重校正；84个真实样本的15/30/60分钟标签手算一致。合成检查包含未来扰动、已收盘时点、同分钟止损优先、跳空、资金费方向与边界、持仓缺失路径无效。审计通过是实现与口径检查通过，不是实盘盈利认证。','',
'实施中统一修复了正确性问题：开盘退出前补做资金费覆盖检查；压力权益计入本分钟实际资金费；EMA只使用第二阶段冻结的特征源，不加载四个仅供标签/结算的离池后补档；小时特征按现货symbol文件定位并核对perpetual contract，避免BONK、PEPE、SHIB的1000单位映射被静默遗漏。前两项在真实回放前修复。EMA修复前的首轮已完成四个成本场景，停止时摘要被动暴露，保存在superseded_market_ema_attempt；修复前后2,221个信号相同。随后独立全rank重建发现三币遗漏，上一轮全部五场景改列不适合最终比较，保存在superseded_symbol_mapping_attempt，修复映射并对齐全池后统一再执行五场景。没有据收益选参数、删方向或改变门槛。','',
'首次修复后execution_freeze的account_outcomes_seen=False字段存在语义错误，已追加元数据更正而未抹除旧记录；最终运行须明确承认先前尝试结果已暴露。因此不能把技术修复重跑称为从未看过账户结果，能主张的是修复原因与规则固定、旧结果留存、最终统一口径。','',
'最终回放前还将已知隔离状态前置到小时排名，防止币安人生在已知禁用后继续占用top3名额；按隔离已知时间判断，不回溯删除此前记录。当小时排名早于缺失已知时间时保留当时排名，但订单在隔离已知后立即拒绝。该修复落实既有可选集规则，没有新增收益阈值。','',
'没有重启、改写或连接实盘；没有访问现有模拟数据库。原模拟代码/配置、前两阶段研究文件的完整性结果见protection_validation.json及integrity_validation.json。完整结果、交易账本、日权益、币种归因、失败检验和修复记录全部保留。','',
'## 后续判断','',
'本轮应保留原模拟，暂不加入这十个新增变量或提升杠杆。F3可作为后续独立验证的风险假设；其余组不应靠在同一批历史上换阈值、换持有期或反复拼组合来宣称有效。若另开研究，优先解决净优势能否覆盖成本，以及特征在真实交易资格内是否存在可解释的条件关系；需要先登记新的少量假设，并使用新增时间段验证。本轮不继续扫描参数。','',
'文件索引：protocol.json（冻结规则）、clarifications_before_outcomes.json（结果前口径）、incremental/selection.json（全部筛选结果）、account/account_results.json（五场景）、account/results/event_baseline/（完整账本）、audit/audit_summary.json（独立审计）、phase3_results.json（总摘要）。','']
lines=[('**'+line[2:]+'**') if line.startswith('# ') else line for line in lines if not line.startswith('## ')]
(P/'第三阶段结果_特征增量与账户回测.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'report':str(P/'第三阶段结果_特征增量与账户回测.md'),'selected_groups':inc['selected_groups'],'five_scenarios':len(scenario_rows),'main_net_pct':main['return_pct']},ensure_ascii=False))

if '--plot' in sys.argv:
    import os
    os.environ['MPLCONFIGDIR']=str(P.parents[1]/'work/phase3-plot-cache')
    sys.path.insert(0,str(P.parents[1]/'work/phase3-report-libs'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    import pandas as pd
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['font.family']=font.get_name();plt.rcParams['axes.unicode_minus']=False
    daily=pd.read_csv(P/'account/daily_accounts.csv')
    fig,axes=plt.subplots(2,1,figsize=(12,8),gridspec_kw={'height_ratios':[1.5,1]})
    for sid,label in scenarios.items():
        d=daily.loc[daily.scenario.eq(sid)].sort_values('date')
        axes[0].plot(pd.to_datetime(d.date),100*(d.last_equity/1000-1),label=label,lw=1.8)
    axes[0].axhline(0,color='#777777',lw=.7)
    axes[0].set_title('完整300日净收益：五种成本情景均亏损，早期触发永久暂停',loc='left',fontweight='bold')
    axes[0].set_ylabel('累计净收益（%）');axes[0].grid(alpha=.16);axes[0].legend(ncol=2,loc='upper right',frameon=False)
    labels=['毛损益','手续费','滑点','资金费','净损益']
    values=[main['gross_pnl'],-main['fees'],-main['slippage_cost'],-main['funding_cost'],main['net_pnl']]
    colors=['#198b69' if v>0 else '#b3424d' for v in values]
    axes[1].barh(labels,values,color=colors,height=.65)
    for i,v in enumerate(values):axes[1].text(v+(1 if v>=0 else -1),i,f'{v:+.2f}',va='center',ha='left' if v>=0 else 'right')
    axes[1].axvline(0,color='#777777',lw=.7);axes[1].set_xlim(-95,25)
    axes[1].set_title('主成本账本：毛收益不足以覆盖交易成本',loc='left',fontweight='bold')
    axes[1].set_xlabel('USDT；起始资金 1,000 USDT');axes[1].invert_yaxis();axes[1].grid(axis='x',alpha=.16)
    for ax in axes:
        ax.spines[['top','right']].set_visible(False)
    fig.text(.08,.015,'历史顺序验证；1×；没有特征通过入选门槛。回撤受原8%永久停机机制限制，不是持续盈利证明。',fontsize=10,color='#555555')
    fig.tight_layout(rect=(0,.045,1,1));fig.savefig(P/'净收益与成本拆解.png',dpi=160);plt.close(fig)
