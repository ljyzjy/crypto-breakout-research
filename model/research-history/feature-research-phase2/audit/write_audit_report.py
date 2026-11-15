from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path(__file__).resolve().parents[1];OUT=Path(__file__).resolve().parent
read=lambda n:json.loads((OUT/n).read_text(encoding='utf-8'))
c=read('causality.json');s=read('stability.json');v=read('coverage_independent.json');fix=read('corrections.json');matched=read('matched_independent.json')
same_hash=hashlib.sha256((ROOT/'features.py').read_bytes()).hexdigest()==c['features_sha256']==s['features_sha256']
assert same_hash,'Audit sources differ; affected audit must rerun'
def pct(x):return 'NA' if x is None else f'{100*x:.2f}%'
def num(x):return 'NA' if x is None else f'{x:.4f}'
lines=[
 '十二项特征：独立实时性、覆盖与识别稳定性审计',
 '完成时间（UTC）：'+datetime.now(timezone.utc).isoformat(),
 '',
 '结论范围',
 '本审计检查特征在历史时点是否只依赖已完成数据、输入缺失是否传播、已发布数值是否会被未来改写，以及小幅改变预登记窗口后的识别敏感性。没有计算未来收益标签、净收益、MFE/MAE结果、拟合预测模型或运行账户回测。现有模拟未改动。',
 '这些结果不能证明策略盈利、可秒级成交或实盘回撤一定小于15%。月档回放也没有原始接收延迟记录。',
 '',
 '一、实时性与公式核验',
 f"独立检查 {len(c['tests'])} 项，通过 {sum(x['passed'] for x in c['tests'])} 项。具体每项范围与结果见causality.json。",
 '直接按独立数组和OLS最小二乘重算720小时回归、6小时隔离、24小时残差样本标准差；另核对6小时路径效率与运动集中度。',
 '独立重算前一完整15分钟ATR14、20个同UTC小时成交额/笔数RVOL，以及半点和任意分钟相位的60分钟相对实现波动。',
 '检查未收分钟/15分钟/小时不可见；未来输入扰动与截断前缀不得改变之前发布的值；缺分钟、零量、平价、历史不足及BTC自身残差均按定义处理。',
 '事件B/A在突破时冻结，第5根后续分钟收盘（t0开盘+6分钟）才发布四项事件特征；检验多空镜像、回到边界内的失败事件仍保留、每币60分钟去重，以及缺测量数据不被当有效。',
 '待测量事件的次日资格和未来隔离状态保持未知，不能先公布未来元数据。已完成但失去资格的事件保留记录，由共同比较掩码排除。',
 '',
 '二、真实输入的有限抽核'
]
real=next((x for x in c['tests'] if x['test']=='deterministic_real_contract_prefix_mutation'),None)
if real and real['passed']:
    for r in real['detail']:
        lines.append(f"{r['contract']}：输入{r['input_rows']:,}分钟；核对{r['hour_rows_checked']:,}小时（其中残差finite为{r['residual_available_checked']}）、{r['minute_rows_checked']:,}分钟上下文和{r['published_event_rows_checked']:,}个已发布事件；截断/扰动结果一致。")
    lines.append('币种和时间规则由覆盖/数据质量特征预先指定，不根据收益挑选。FTM额外围绕首个观测到的零成交分钟，其他币使用首段可用历史。真实前缀测试不是对全部时间和一切异常的穷尽证明。')
else:lines.append('真实输入抽核未通过或未完成，不得以合成测试替代真实数据审计。')
repair=next((x for x in c['tests'] if x['test']=='repaired_AXS_BIO_finite_residual_prefix_mutation'),None)
if repair and repair['passed']:
    lines.append('为防止原缺口币仅比较NA而没有验证可计算路径，另外按最早finite残差时点检查AXS/BIO，不依据收益选时点：')
    for r in repair['detail']:
        lines.append(f"{r['contract']}：全部输入小时finite残差{r['finite_residual_all_hours']}个、资格期间{r['finite_residual_qualified_hours']}个；{r['status']}。")
    lines.append('BIO即使在后来输入区间能算出残差，也不代表其资格期间已经补足；资格期仍缺失必须保持NA，不可把后来可得值提前填回。')
lines += [
 '',
 '三、全部产物的覆盖与时点包络',
 f"检查{v['files_checked']}个clock/event产物文件，时钟队列{v['actual_rows']['clock']:,}条，事件队列{v['actual_rows']['event']:,}条；原始日池应有时钟机会{v['expected_raw_clock_rows']:,}条。",
 f"文件哈希、ID唯一性、逐币原始机会数量、数值范围、事件发布/去重和已知时间包络检查：{'通过' if v['all_passed'] else '存在未解决问题，见coverage_independent.json'}。",
 '无映射币的机会必须保留为不可评估行，不能靠删币提高覆盖率。已知时间<=决策时点是静态包络检查，还需结合前述独立前缀/公式核验理解。',
 f"六组比较掩码独立重建核对：{'全部一致' if matched['all_passed'] else '存在未解决差异'}。从原始特征产物重新计算资格、控制变量、组内变量和65分钟边界后，检查纳入ID、排除行及基准/增强ID摘要。仍未生成未来标签，后续标签可得性需要再次两边同步检查。",
 '',
 '四、预登记邻域敏感性（只变一个维度）',
 f"覆盖{s['scope']}，共{len(s['contracts'])}个合约；没有新增或择优参数，没有收益检验。"
]
for row in s['aggregate_hourly']:
    k=row['variant_hours'];vv=row['variables']
    lines.append(f"背景6h→{k}h：自身方向收益Pearson {num(vv['r6']['pearson'])}，方向符号不一致{pct(vv['r6']['sign_disagreement_fraction'])}；路径效率Spearman {num(vv['efficiency6']['spearman'])}；集中度Spearman {num(vv['concentration6']['spearman'])}。")
lines.append('上述窗口敏感性没有改变残差自身6/720/24规格；残差相关为1是构造不变，不能作为它对回归/隔离窗口稳健的证据。')
for row in s['aggregate_events']:
    lines.append(f"边界20m→{row['variant_lookback_minutes']}m：基准{row['base_events']:,}事件、变体{row['variant_events']:,}事件，精确同起点/同方向交集{row['exact_intersection']:,}，Jaccard {pct(row['jaccard'])}，基准保留{pct(row['base_retained_fraction'])}。")
lines += [
 '事件统计按事先可识别的起点计，包含失败或尚未完成测量的事件；它不是交易数。窗口改变还会改变“60分钟只留最早事件”的去重起点，使后续事件时钟发生连锁位移，低Jaccard不能全部归因于价格边界几何本身。按同方向15分钟内一对一近邻配对的时间偏移仅作描述，不保证两个事件对应同一经济过程。',
 '本阶段没有事前设定最低相关系数/Jaccard，所以不会事后选一个阈值宣称通过或失败。低重合提示边界定义敏感，高重合也不能证明有净收益优势。主规格仍为6h背景与20m边界。',
 '',
 '五、技术纠错记录',
 '首次独立测试发现DatetimeIndex时间分辨率假设错误，显式毫秒转换后已复跑。静态复核发现pending事件可能提前显示未来日池/隔离状态，改未知后通过跨午夜测试。',
 '实现者还报告无映射UUSDT的空数据dtype问题，修为保留不可评估行；独立全量产物检查核对其原始机会分母。测试脚本自身的ts索引/列歧义和状态列名称适配也独立记录，数学预期与容差未改。',
 '父代理复核还将1个跨开发截止的待测量事件保留在排除掩码中；入选样本未因此改变。掩码改为临时文件写完后原子替换并以READY标记完整，独立ID重建在最终版本上通过。',
 '最终通过不表示首次实现无缺陷；纠错未使用收益结果、未修改原模拟。详细归属和复跑范围见corrections.json。',
 '',
 '可复现入口',
 'run_causality.py --real：合成oracle与指定真实样例的前缀/未来扰动。',
 'run_stability.py：全部映射合约的预登记单维窗口比较。',
 'check_cohorts.py：全部成品的哈希、覆盖、值域和时点包络。',
 'features.py审计版本SHA256：'+c['features_sha256'],
 '数值等同性容差：绝对1e-10，相对1e-9。源文件与测试脚本摘要保存在各JSON中。'
]
(OUT/'审计结论.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
summary={'utc':datetime.now(timezone.utc).isoformat(),'finite_causality_checks_passed':c['all_passed'],'full_cohort_checks_passed':v['all_passed'],'matched_mask_reconstruction_passed':matched['all_passed'],'real_sample_checks_passed':bool(real and real['passed']),'stability_complete':True,'same_features_hash':same_hash,'profitability_assessed':False,'tests':len(c['tests']),'contracts_in_stability':len(s['contracts']),'script_outputs':['causality.json','stability.json','coverage_independent.json','matched_independent.json','corrections.json','审计结论.txt']}
(OUT/'audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
