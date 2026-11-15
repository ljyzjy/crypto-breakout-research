"""Summarize completed data/feature audits. Reads no future-outcome labels."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path(__file__).resolve().parent
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

d=read('data/data_validation.json');legacy=read('feature_outputs/legacy_coverage_comparison.json')
overlap=read('feature_outputs/overlap_numeric_validation.json');causal=read('audit/causality.json')
coverage=read('audit/coverage_independent.json');stable=read('audit/stability.json')
matched=read('matched_samples/summary.json');independent=read('audit/matched_independent.json')
btc=read('feature_outputs/residual_missing_btc_attribution.json');protected=read('protection_validation.json')
feature_manifest=read('feature_outputs/manifest.json')

# Cross-file verification of the final, fully built versions.
assert protected['unchanged'] and protected['files_checked']==410
assert d['manifest_sha256']==sha(ROOT/'data/manifest.json')==feature_manifest['source_manifest_sha256']==matched['data_manifest_sha256']
assert read('data/READY.json')['manifest_sha256']==sha(ROOT/'data/manifest.json')
assert read('feature_outputs/READY.json')['manifest_sha256']==sha(ROOT/'feature_outputs/manifest.json')
assert not read('feature_outputs/READY.json')['partial']
assert read('matched_samples/READY.json')['summary_sha256']==sha(ROOT/'matched_samples/summary.json')
assert independent['matched_summary_sha256']==sha(ROOT/'matched_samples/summary.json')
assert feature_manifest['features_sha256']==causal['features_sha256']==stable['features_sha256']==sha(ROOT/'features.py')
assert causal['all_passed'] and coverage['all_passed'] and independent['all_passed'] and overlap['all_passed']
assert coverage['actual_rows']['clock']==481*20*48==461760
assert coverage['actual_rows']['event']==195996
assert all(g['identical_comparison_ids'] and g['baseline_id_sha256']==g['enhanced_id_sha256'] for g in matched['groups'])
assert all(g['all_cohort_records']==195996 for g in matched['groups'] if g['cohort']=='events')
assert len(stable['contracts'])==60 and stable['new_parameter_selection'] is False
assert d['required_missing_minutes']==0 and d['daily_pool_rebuild_equal'] and d['all_original_trade_values_identical']
assert btc['F1_clock_blank_days']==73 and btc['F1_clock_active_days']==408
assert btc['residual_missing_total']==legacy['non_btc_rows']-legacy['new_residual_available']==38950
assert btc['fit_failure_attribution_counts']['both']==34029
assert btc['fit_failure_attribution_counts']['own_coin_only']==4669
assert btc['fit_failure_attribution_counts']['BTC_only']==0
assert btc['both_bad_fit_rows_with_shared_same_invalid_hour']==34029

oldpct=legacy['old_residual_available']/legacy['non_btc_rows']*100
newpct=legacy['new_residual_available']/legacy['non_btc_rows']*100
oldvol=legacy['old_quote_rvol_available']/legacy['exact_old_index_rows']*100
newvol=legacy['new_quote_rvol_available']/legacy['exact_old_index_rows']*100
names={'F1':'自身6h收益、BTC残差','F2':'路径效率、单段运动集中度','F3':'相对波动、ATR标准化振幅','F4':'边界距离、外侧停留比例','F5':'当前逆向深度、恢复比例','F6':'成交额RVOL、笔数RVOL'}
hourly={x['variant_hours']:x['variables'] for x in stable['aggregate_hourly']}
events={x['variant_lookback_minutes']:x for x in stable['aggregate_events']}
table=[{'group':g['group'],'features':names[g['group']],'cohort':g['cohort'],
        'original_records':g['all_cohort_records'],'matched_records':g['matched_observations'],
        'days':g['active_utc_days'],'symbols':g['symbols'],
        'feature_coverage':g['group_feature_coverage'],'matched_coverage':g['matched_share_of_feature_eligible'],
        'sample_min_pass':g['minimum_record_requirements_pass'],'coverage_threshold_pass':g['matched_coverage_threshold_pass']}
       for g in matched['groups']]

summary={
 'completed_at_utc':datetime.now(timezone.utc).isoformat(),
 'status':'Completed historical warmup, unified data, twelve features, per-group matched samples, causal/coverage/stability audits.',
 'research_period':'[2025-01-01T00:00:00Z,2026-04-27T00:00:00Z),481 days; previously explored development data',
 'data_version':'warmup32-v1','data_manifest_sha256':sha(ROOT/'data/manifest.json'),
 'feature_manifest_sha256':sha(ROOT/'feature_outputs/manifest.json'),
 'new_monthly_archives':79,'normalized_minute_rows':d['normalized_rows'],'required_minute_gaps':0,
 'feature_count':12,'clock_opportunities':461760,'boundary_events':195996,
 'legacy_coverage':{'residual_before_pct':oldpct,'residual_after_pct':newpct,'residual_gain_pp':newpct-oldpct,
    'residual_available_added':11251,'rvol_before_pct':oldvol,'rvol_after_pct':newvol,'rvol_added_each':7044,
    'old_available_residual_lost':0,'overlap_numeric_checks_passed':True},
 'paired_comparison_groups':table,
 'causal_audit':{'checks_passed':len(causal['tests']),'real_contracts':['BTCUSDT','ETHUSDT','1000PEPEUSDT','AXSUSDT','BIOUSDT','FTMUSDT'],
    'additional_repaired_finite_cases':['AXSUSDT','BIOUSDT'],'all_completed_checks_passed':True,
    'scope_limit':'Finite independent synthetic/oracle/prefix/future-mutation checks plus all output timestamp/key checks; no exhaustive mathematical proof or live message-delay test.'},
 'stability':{'contracts_tested':60,'hourly':stable['aggregate_hourly'],'events':stable['aggregate_events'],
    'verdict':'Theoretical-time reproducibility checks passed. Window sensitivity is material for direction labels, path efficiency and event starts; no post-hoc robustness threshold or parameter winner is chosen.',
    'residual_window_robustness_tested':False,'unchanged_main_hours':6,'unchanged_boundary_minutes':20},
 'remaining_missing':{'non_btc_residual_hours':38950,'fit_both_invalid':34029,'fit_own_only_invalid':4669,'fit_BTC_only_invalid':0,
    'recent6_invalid':252,'btc_archived_zero_minutes':37,'btc_invalid_hours':4,'common_blank_days':73,
    'blank_day_ranges':['2025-01-15 through2025-02-27','2025-08-30 through2025-09-27'],
    'interpretation':'Shared invalid observations in both BTC and coins, amplified by strict contiguous-window eligibility; not missing archive downloads or proof of exchange outage cause. Relaxing the rule was not performed.'},
 'protected_original_files_unchanged':410,'old_paper_strategy_changed':False,'paper_database_accessed':False,
 'website_changed':False,'new_account_backtests':0,'forward_labels_built':False,'forward_validation_started':False,
 'ready_for':'Predeclared incremental-information tests on development data with coverage caveats and identical group-specific samples; no claim of predictive or net-profit edge.',
 'not_established':['net profitability','live receive/execution latency','second-level execution','5x liquidation safety','future maximum drawdown below15%','parameter robustness for residual/volatility/activity windows not perturbed in this audit']
}
(ROOT/'phase2_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

lines=[
 '第二阶段结果：历史预热、十二项特征与因果审计',
 '完成日期：2026-11-13。状态：本轮任务完成；没有新账户收益回测、未来收益标签、实盘连接或模拟切换。',
 '',
 '结论',
 '历史预热已补足，十二项特征已实现，统一比较样本与因果时点检查通过。仍有两个需要正视的限制：残差的严格连续历史有效性会造成长期共同缺失，突破事件入口对边界窗口敏感。没有通过放宽规则或选择更赚钱参数来掩盖这些问题。',
 '本轮验证的是数据与计算条件，不是策略已经有盈利能力。研究段仍为已多次使用的2025-01-01—2026-04-26开发历史，不是新样本外。',
 '',
 '一、并行任务与数据版本',
 '数据代理完成下载计划、CHECKSUM、9字段标准化与加载接口；实现代理完成12特征和完整队列；独立代理完成公式、前缀、未来扰动、全量产物及窗口敏感性检查；主代理建立逐组共同样本、交叉核验并冻结交付。',
 'warmup32-v1：509个成交月档，其中430个复用原冻结档、79个新增过去档；新增ZIP约129.4MB，标准化22,225,504条分钟记录。原资格日及此前32完整UTC日的必要成交分钟缺行0。',
 '原481日日池重建完全一致；60个永续合约的映射范围不扩大；旧867个标记价/资金费文件只读复用与校验。59,378个零量分钟保留，不能填成有交易。',
 '统一加载器必须看到READY并核验manifest哈希；截止2026-04-27 00:00 UTC为半开边界。4个旧离池后跨月缓冲档仍保留在原目录，后续构造持仓退出/未来标签时须显式复用，不能因本轮只计算过去特征而把退出记录删掉。',
 'UUSDT无映射仍保留不可评估行；币安人生沿原已知时间隔离，原记录和此前损失不追溯删除。',
 '',
 '二、同一旧索引上的真实覆盖改善',
 f"非BTC残差：{legacy['old_residual_available']:,}/{legacy['non_btc_rows']:,}（{oldpct:.2f}%）→{legacy['new_residual_available']:,}/{legacy['non_btc_rows']:,}（{newpct:.2f}%）；新增11,251币小时，提升{newpct-oldpct:.2f}个百分点。",
 f"成交额RVOL与笔数RVOL各自：221,022/230,424（{oldvol:.2f}%）→228,066/230,424（{newvol:.2f}%）；各新增7,044币小时。",
 '旧版可计算的残差没有丢失。r6、残差、成交额RVOL、笔数RVOL在重叠可用观测上均通过atol=1e-10、rtol=1e-9的一致性检查；残差最大绝对差4.28e-12。覆盖提升来自输入补足，公式未为此改变。',
 '',
 '三、仍缺的残差意味着什么',
 '非BTC仍有38,950资格小时不可计算：34,029个为BTC与本币拟合窗同时失效，4,669个仅本币失效，0个仅BTC失效，另252个拟合窗有效但最近6小时不完整。',
 '34,029个共同失效窗口均存在BTC与本币在同一小时的无效收益，所以不能把这些行单独归因于BTC。所需原始分钟已无下载缺行；这里的问题主要是严格的有效性定义及其传播。',
 'BTC档案中37个零成交分钟分布于4个小时，使7个小时收益不可用，再被720连续有效配对小时及6小时隔离放大。归档记录本身不足以确定交易所停机等原因。',
 '当前F1共同队列在481天中只有408个活跃日；完整空白日为2025-01-15—02-27（44天）及2025-08-30—09-27（29天），合计73天。',
 '此前残差全缺的七币：ETHFI、TON、VIRTUAL现资格期100%可计算；AXS72.22%、SEI47.36%；BIO、JUP仍0。BIO在离池后有有限残差，不能提前填回资格期。',
 '本轮保留严格规则，不用更早数据替代固定窗口内无效记录，不填零，也不把残差缺失当作反向信号。下一步检验须保留这种选择性覆盖，不能把其余特征一并裁到残差样本。',
 '',
 '四、十二项实现与可比较样本',
 '原固定时间队列完整保留461,760条（481天×20币×48次）；边界队列保留195,996个事件，包括失败、不可评估、离池和一个跨研究截止的待测量事件。',
 '每组基准与增强使用同一份ID掩码；不同组不强行取全12项交集。共同控制、可知时点、方向、资格和末尾65分钟隔离统一应用。以下是观测数，不是交易笔数或独立样本数：',
]
for g in table:
    lines.append(f"{g['group']} {g['features']}：共同样本{g['matched_records']:,}，{g['days']}个活跃日、{g['symbols']}币；共同样本ID独立重建一致。")
lines += [
 '六组均达到事前80%覆盖和200观测/30日/8周/5币的最低记录门槛。这些工程门槛不是功效保证，不能解释为通过盈利筛选；后续真正构造结果标签时仍要对缺失结果重新做同组匹配。',
 '',
 '五、实时性与因果检查',
 f"独立{len(causal['tests'])}项检查全部通过：过去720h OLS与24h残差标准化、ATR、同UTC基准、60分钟波动、未收K线、缺失零量、多空镜像、失败事件保留、前缀重算与未来扰动。",
 '真实样例固定BTC、ETH、1000PEPE、AXS、BIO、FTM，每币约800小时、2,880分钟上下文、40个已发布事件；另外按最早有限残差时点检查AXS/BIO，避免仅靠NA不变判断正确。',
 '全部122个时钟/事件文件完成ID、哈希、原分母、值域与可知时间包络检查。突破minute若12:00开盘，第5根后续bar到12:06才完成测量，不能在12:00入场时提前使用。半点波动只用已完成60分钟，不偷用未收整点小时。',
 '发现并修复的技术问题已留记录：日期分辨率导致毫秒被缩小、待测事件提前显示未来资格/隔离、无映射空表类型、跨截止待测事件的保留，以及比较文件并发读取的完成标志。修复后复跑对应检查，没有用未来净收益选择修复方式。',
 '本结论覆盖已执行的合成、抽样真实与全量产物检查，不是所有可能输入的穷尽证明。月档无原始接收时戳，理论bar可知时间通过不等于实盘接收延迟或秒级成交已验证。',
 '',
 '六、稳定性结果：发现敏感性，主规格保持不变',
]
for k in (5,7):
    v=hourly[k]
    lines.append(f"6h背景改为{k}h：自身收益Pearson {v['r6']['pearson']:.4f}；正/负/零符号不一致{100*v['r6']['sign_disagreement_fraction']:.2f}%；路径效率Spearman {v['efficiency6']['spearman']:.4f}；运动集中度Spearman {v['concentration6']['spearman']:.4f}。")
for k in (15,25):
    v=events[k]
    lines.append(f"20m边界改为{k}m：事件集合Jaccard {100*v['jaccard']:.2f}%；同币、同方向、同一突破分钟的原事件精确保留{100*v['base_retained_fraction']:.2f}%（{v['exact_intersection']:,}/{v['base_events']:,}）。")
lines += [
 '以上覆盖全部60映射合约，单次只改一个预登记窗口。事件差异还包含60分钟最早事件去重起点变化，不能把所有变化都归因于边界价格，也不能说未精确重合的事件就代表不同的经济走势。',
 '因此，方向硬门槛与事件入口存在敏感性；持续型背景分数和边界事件的稳定性应分别理解。没有按这些数字改为5h/7h/15m/25m，更没有计算哪个参数更赚钱。主规格仍6h与20m。',
 '残差自身6/720/24参数未变，所以其相关等于1只是构造不变，不是参数稳健性证据。波动与活跃度窗口也未扩展扫描；本轮不对未测窗口的稳健性作结论。',
 '',
 '七、现有模拟与下一步边界',
 '410个受保护的旧策略/配置/研究登记及网页相关文件前后哈希相同；未访问模拟数据库、未下单、未启动新模拟、未激活5×，未改网页。',
 '本轮没有未来收益标签、预测模型增量检验或账户回测，所以没有新的年化、最大回撤和净收益结果。补足覆盖与通过时点检查不证明因子有收益。',
 '下一步可在同组共同样本上检验预登记的30分钟增量信息，再做同成本净收益比较。残差的共同缺口和边界入口敏感性必须纳入解释，不能把识别分数直接当作胜率或加杠杆依据。',
 '完整策略、预测拟合与执行实现尚未冻结，前向90+90日窗口仍未启动。已使用历史仍为开发样本。',
 '',
 '交付索引',
 'phase2_results.json：结果与限制的机器可读汇总；freeze_manifest.json：最终交付的完整性摘要。',
 '特征字典.txt：十二项公式、可知时点与缺失处理。data/数据版本说明.txt：数据范围与校验。',
 'audit/审计结论.txt：独立因果、全量覆盖、共同样本和窗口敏感性审计。',
 'matched_samples/比较样本说明.txt：逐组匹配及剔除原因。feature_outputs/BTC共同参考缺失归因.txt：73个共同空白日的来源。',
 '各脚本和parquet保留在相应目录，可按manifest复核。SHA256用于本地完整性校验，不是第三方时间戳或盈利认证。',
]
(ROOT/'第二阶段结果_预热特征与因果审计.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')

text_files=list(ROOT.rglob('*.txt'))
for p in text_files:assert '\ufffd' not in p.read_text(encoding='utf-8'),str(p)
checks={'utc':datetime.now(timezone.utc).isoformat(),'all_cross_file_checks_passed':True,'data_and_feature_versions_consistent':True,'audit_hashes_match_executed_feature_source':True,'paired_ids_independently_checked':True,'coverage_and_counts_reconciled':True,'text_files_utf8_checked':len(text_files),'new_account_backtests':0,'forward_labels':False,'stability_is_not_a_profitability_pass':True}
(ROOT/'deliverable_validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
frozen={'utc':datetime.now(timezone.utc).isoformat(),'scope':'Final phase2 outputs; reused old sources are pinned transitively by data/manifest.json and previous phase hashes. No real-account or performance certification.','files':{}}
for p in sorted(ROOT.rglob('*')):
    if not p.is_file() or '__pycache__' in p.parts or p.name=='freeze_manifest.json' or p.name.endswith('.tmp'):continue
    frozen['files'][str(p.relative_to(ROOT)).replace('\\','/')]={'sha256':sha(p),'size':p.stat().st_size}
(ROOT/'freeze_manifest.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'completed':True,'frozen_files':len(frozen['files']),'residual_before_pct':oldpct,'residual_after_pct':newpct,'rvol_before_pct':oldvol,'rvol_after_pct':newvol,'causality_checks':len(causal['tests']),'stability_contracts':len(stable['contracts']),'original_files_unchanged':410,'new_account_backtests':0}))
