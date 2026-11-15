from common import *
from datetime import datetime,timezone
import shutil

def main():
    accounts=read(OUT/'account_results.json');audit=read(OUT/'audit.json');opps=read(OUT/'diagnostics/opportunity_results.json');paired=read(OUT/'diagnostics/paired_summary.json')
    assert audit['passed'] and accounts['A_exact_reproduction']
    a=accounts['results'][0];ev={x['variant']:x for x in opps['results'] if x['split']=='evaluation'}
    summary=pd.DataFrame([{k:r.get(k) for k in ['run_id','scenario','signal_candidates','trades','net_win_count','net_win_rate_pct','net_pnl','return_pct','max_drawdown','intrabar_stress_dd','profit_factor','active_calendar_days','fully_cash_calendar_days','acceptance_pass']} for r in accounts['results']])
    summary.to_csv(OUT/'账户比较汇总.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(opps['results']).drop(columns='label_status').to_csv(OUT/'筛选器与机会诊断.csv',index=False,encoding='utf-8-sig')
    text=f'''# B、C 两个版本回测报告

结论：两个版本均未达到“净胜率至少60%、净收益为正、最大回撤不超过15%”的目标。B与C在固定65%概率门槛及正净期望门槛下均无合格信号，账户实际成交均为0笔。净胜率不可计算；零收益、零回撤来自全程空仓，不能认定为成功或实盘成本稳健。

本轮完成了信号生成、模型训练、独立概率校准、300天账户回放、五种成本场景、执行标签对账与来源保护检查。未改动现有模拟，未访问模拟数据库，未接入交易接口。

## 统一范围与规则

- 数据：沿用第三阶段的60个映射永续合约、历史每日现货流动性池和已冻结预热数据。历史池不等于今天所有币安永续合约。
- 训练：2025-01-01至2025-03-31，90天。
- 概率校准及盈亏金额估计：2025-04-01至2025-06-30，91天。
- 账户评估：2025-07-01至2026-04-26，300天；统一1000 USDT起始资金。
- 训练及校准边界均剔除决策后65分钟可能跨段的样本；实际标签退出时间也必须早于边界。
- 单一L2逻辑回归，不做模型、参数、门槛、币种或止盈网格搜索。各版本仅训练一次，随后仅在校准段拟合概率校准，不在评估期重训。
- 特征共16列：方向调整的6小时收益、24小时收益、BTC 24小时收益、BTC残差动量；残差缺失标识、BTC标识；边界距离、边界外接受比例、回撤、恢复；3分钟主动成交失衡、3分钟价格推进；成本/止损距离比、相对成交量、ATR/价格、交易方向。
- 残差缺失使用训练期中位数并保留缺失标识；BTC自身残差结构性缺失另行标识。其余输入不得缺失。没有用未来价格补全特征。
- 主成本：单边手续费0.05%＋单边不利滑点0.05%，合计往返约0.20%，另计历史资金费率。手续费是延用的公开费率假设，并未核验账户VIP费率；滑点为模型估计。
- 压力场景：手续费2倍、手续费3倍、滑点2倍、额外延迟1分钟；不重新训练或调整门槛。
- 风控：沿用1×名义敞口上限、2R止盈、结构止损、最长60分钟持有、日内收盘、相关性及仓位约束。回撤5%减半风险，回撤8%永久停机，未放宽保护以凑足样本。
- 原历史已经被研究过，本次属于按时间划分的回顾性检验，不能声称为从未查看的新样本。未来90＋90天协议未启动。

## 两个版本的准确区别

B：保留原来的突破后五根后续K线观察窗口及原入场方式，第二层筛选器仅在校准后净盈利概率至少65%、估计净期望大于0时放行。评估期2,282条基线信号与原基线逐字段完全一致。

C：采用相同的初始突破事件队列。突破边界B及ATR值A在突破时固定；初始突破K线之后，必须有一根K线触及[B−0.25A,B＋0.25A]，随后另一根已收盘K线重新站在边界外，并越过上一根K线向交易方向的极值。确认必须在初始突破收盘后15分钟内完成；向错误方向收盘超过0.25A则取消。确认后的下一分钟入场。止损采用突破至确认期间极值外0.1A，保留原有止损距离及成本空间检查。C按自己的入场、止损与资金费路径重新生成标签、训练和校准。

两版本标签采用独立单位名义本金机会：止盈、止损、时间到期、日内收盘、滑点、手续费、资金费都参与净盈利判断。机会标签不施加依赖账户历史的仓位占用、每日亏损暂停及账户永久停机；这些约束在最终账户回放中完整保留。因此下面的机会诊断不能冒充组合交易结果。

## 账户结果

| 主成本版本 | 实际交易 | 净胜率 | 净利润/USDT | 总收益 | 最大回撤 | 活跃交易日 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| A 原基线 | {a['trades']} | {a['net_win_rate_pct']:.2f}% | {a['net_pnl']:.2f} | {a['return_pct']:.2f}% | {a['max_drawdown']:.2f}% | {a['active_calendar_days']} | 未通过 |
| B 筛选器 | 0 | 不可计算 | 0.00 | 0.00% | 0.00% | 0 | 未通过，样本不足 |
| C 回踩＋筛选器 | 0 | 不可计算 | 0.00 | 0.00% | 0.00% | 0 | 未通过，样本不足 |

A的8%附近回撤伴随永久停机，不是证明持续交易能维持低回撤。B、C均完整回放300天，300天全为空仓，利润因子与胜率均不具备有效交易样本。五种成本场景均无成交；不能据此认定成本承受能力通过。300天低于一年，沿用原协议不报告经外推的年化收益。

## 为什么没有交易

| 评估期指标 | B | C |
|---|---:|---:|
| 筛选前候选机会 | {ev['B']['candidates']} | {ev['C']['candidates']} |
| 特征完整机会 | {ev['B']['feature_valid']} | {ev['C']['feature_valid']} |
| 校准后最高净盈利概率 | {100*ev['B']['max_probability_all_candidates']:.2f}% | {100*ev['C']['max_probability_all_candidates']:.2f}% |
| 校准前最高原始概率 | {100*ev['B']['max_raw_probability_all_candidates']:.2f}% | {100*ev['C']['max_raw_probability_all_candidates']:.2f}% |
| 固定概率门槛 | 65% | 65% |
| 同时通过概率及净期望门槛 | 0 | 0 |
| 评估期AUC | {ev['B']['auc']:.4f} | {ev['C']['auc']:.4f} |

两版本特征覆盖率均为100%，所以没有成交不是缺少全部输入或导出失败。残差本身缺失时使用已登记的训练中位数加标识；评估期缺失比例分别为{ev['B']['residual_missing_pct']:.2f}%、{ev['C']['residual_missing_pct']:.2f}%。

AUC衡量模型是否能把盈利机会排在亏损机会之前，0.5约等于无区分能力。当前两个模型都接近0.5。B训练AUC约0.597，评估AUC约0.507；C训练约0.572，评估约0.511，区分能力没有稳定延续。独立校准把预测概率压回接近实际的约三成水平。连未校准的最高预测概率也未达到65%，因此结果并非单纯由校准造成。

## 真实回踩有没有改善

以下是执行资格成立的独立假想机会，允许时间重叠，不是实际账户持仓，不能相加成账户收益。

| 未应用筛选器的机会诊断 | B入场方式 | C真实回踩 |
|---|---:|---:|
| 评估期可执行机会 | {ev['B']['executable_labels']} | {ev['C']['executable_labels']} |
| 净胜率 | {ev['B']['net_win_rate_pct']:.2f}% | {ev['C']['net_win_rate_pct']:.2f}% |
| 平均单机会净收益/名义本金 | {ev['B']['mean_net_bp']/100:.4f}% | {ev['C']['mean_net_bp']/100:.4f}% |
| 平均净收益/初始价格风险R | {ev['B']['mean_net_R']:.4f}R | {ev['C']['mean_net_R']:.4f}R |

在同一次初始突破、B与C都可执行的{paired['n']}个交集机会里，B净胜率{paired['B_net_win_rate_pct']:.2f}%，C为{paired['C_net_win_rate_pct']:.2f}%，差约{paired['C_net_win_rate_pct']-paired['B_net_win_rate_pct']:.2f}个百分点；C平均净收益改善{paired['mean_C_minus_B_net_bp']:.2f}个基点，但两者仍为负。该交集是事后执行诊断，不用于筛选账户信号，也不能将其当作因果优越性证明。

可执行机会的平均毛优势很弱：B约−0.49个基点，C约＋0.64个基点，相比约20个基点的往返费用和滑点明显不足。因此当前证据支持：真实回踩带来的局部改善很小；现有特征＋固定模型尚不能识别足够可靠的盈利子集。不能由本次失败推断所有筛选模型或回踩策略均无效。

## 审计与限制

- B信号重建与原评估集2,282条完全一致；原A账户主成本结果也复现。
- {audit['prefix_checks']}项截断未来数据后的特征及信号检查通过。
- C全部信号均满足：回踩K线先完成、后续确认K线再完成、之后才入场。
- B与C训练最大标签时间均早于4月1日，校准最大标签时间均早于7月1日。
- 8项独立标签与原账户引擎单笔回放对账通过，包含止盈、止损、时间退出和资金费样例。
- 已完成11次账户回放：A主成本复现，B与C各五种成本。每次均覆盖432,000分钟，资金与交易账一致。
- {audit['source_files_verified']}个既有源文件、配置或冻结研究文件核对未变；未访问现有模拟数据库。
- 中途只修复了只读数组兼容、NumPy数值JSON导出，以及单笔审计跨UTC午夜时测试窗口太短三个实现问题。没有改动交易门槛、模型参数、入场/退出规则或训练区间。日志及修复记录保留。
- 两版本没有成交，不能计算有意义的账户胜率置信区间；初步至少100笔、30个活跃日的要求未满足。
- 市场数据缺少历史订单簿、真实排队及账户费率，未声称秒级成交或真实账户成交认证。

## 研究决定

本轮B、C均不满足替换现有模拟的条件。保留65%门槛和全部失败结果，不降低门槛、不改止盈止损来追求60%胜率。现阶段证据指向基础交易机会的净期望和特征区分能力不足；继续增加杠杆无法解决这些问题。

协议SHA256：`{sha(OUT/'protocol.json')}`。

主要文件：`protocol.json`、`account_results.json`、`audit.json`、`diagnostics/opportunity_results.json`、`predictions/all.parquet`、`models/`、`accounts/`。`source_snapshot/`为本次执行代码快照，原相对目录布局为`work/winrate60/`，不得将快照直接作为会覆盖既有冻结输出的重跑入口。
'''
    (OUT/'B_C回测结果与诊断.md').write_text(text,encoding='utf-8')
    sys.path.insert(0,str(BASE/'work/phase3-report-libs'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc');plt.rcParams['font.family']=font.get_name();plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,3,figsize=(16,5.5),gridspec_kw={'width_ratios':[1.15,1.1,1]});fig.patch.set_facecolor('#f5f7fa')
    fig.suptitle('B / C 回测：固定门槛下均为零交易，未达到目标',fontsize=17,fontweight='bold',y=.99)
    for v,color in [('A','#c95858'),('B','#2c6fb7'),('C','#27977a')]:
        c=pd.read_parquet(OUT/f'accounts/{v}/main-curve.parquet').iloc[::1440]
        axes[0].plot(pd.to_datetime(c.ts,unit='ms',utc=True),c.equity,label=v+' '+{'A':'原基线','B':'筛选器','C':'回踩＋筛选器'}[v],color=color,linestyle='--' if v=='C' else '-',linewidth=2)
    axes[0].set_title('实际账户净值 · 起始 1,000 USDT');axes[0].set_ylabel('USDT');axes[0].legend(fontsize=8);axes[0].tick_params(axis='x',rotation=35)
    p=pd.read_parquet(OUT/'predictions/all.parquet');p=p[p.split.eq('evaluation')]
    for v,color in [('B','#2c6fb7'),('C','#27977a')]:
        axes[1].hist(p.loc[p.variant.eq(v),'probability']*100,bins=np.arange(0,71,2),alpha=.6,label=v,color=color)
    axes[1].axvline(65,color='#c95858',linestyle='--',label='固定门槛65%');axes[1].set_xlim(0,70);axes[1].set_title('校准后的预测概率 · 全部候选');axes[1].set_xlabel('预测净盈利概率 / %');axes[1].set_ylabel('候选机会数');axes[1].legend(fontsize=8)
    vals=[ev[v]['net_win_rate_pct'] for v in ['B','C']];bars=axes[2].bar(['B入场','C真实回踩'],vals,color=['#2c6fb7','#27977a'],width=.5)
    for b,val in zip(bars,vals):axes[2].text(b.get_x()+b.get_width()/2,val+1.3,f'{val:.2f}%',ha='center')
    axes[2].axhline(60,color='#c95858',linestyle='--',label='净胜率目标60%');axes[2].set_ylim(0,72);axes[2].set_title('未筛选的独立机会净胜率');axes[2].set_ylabel('%');axes[2].legend(fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.18);ax.spines[['top','right']].set_visible(False)
    fig.text(.5,.015,'2025-07-01 至 2026-04-26 | 同一数据与成本 | 右图为重叠机会诊断，不是B/C账户交易胜率',ha='center',fontsize=10,color='#555')
    fig.tight_layout(rect=[0,.06,1,.93]);fig.savefig(OUT/'B_C回测对比.png',dpi=180,facecolor=fig.get_facecolor());plt.close(fig)
    dest=OUT/'source_snapshot';dest.mkdir(exist_ok=True)
    for p in Path(__file__).resolve().parent.glob('*.py'):shutil.copyfile(p,dest/p.name)
    for p in Path(__file__).resolve().parent.glob('*.log'):shutil.copyfile(p,dest/p.name)
    files={str(p.relative_to(OUT)).replace('\\','/'):{'sha256':sha(p),'size':p.stat().st_size} for p in OUT.rglob('*') if p.is_file() and p.name!='deliverable_manifest.json'}
    dump(OUT/'deliverable_manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'files':files,'audit_passed':True,'goal_met':False})
    print('REPORT_READY',len(files),flush=True)

if __name__=='__main__':main()
