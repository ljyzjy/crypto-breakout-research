"""Summarize completed independent checks, keeping performance separate."""
from pathlib import Path
import json, hashlib
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parent;P3=ROOT.parent;ACC=P3/'account'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    inc=read(ROOT/'incremental_independent.json'); sig=read(ROOT/'signals_independent.json')
    ledger=read(ROOT/'account_independent.json'); syn=read(ROOT/'synthetic_methods.json'); exe=read(ROOT/'independent_execution.json')
    report=read(ACC/'account_results.json'); execution=read(ACC/'execution_freeze.json')
    integrity=read(P3/'integrity_validation.json');protection=read(P3/'protection_validation.json')
    assert inc['all_checks_passed'] and sig['all_checks_passed'] and ledger['all_checks_passed'] and exe['all_passed']
    assert all(x['passed'] for x in syn['checks'])
    assert ledger['final_execution_freeze_sha256']==sha(ACC/'execution_freeze.json')
    assert integrity['passed'] and protection['unchanged']
    assert execution['prior_attempt_outcomes_seen'] and execution['current_attempt']=='all_60_symbol_mappings_corrected_v3'
    assert sig['rank_rows_independently_reconstructed']==27014 and sig['candidate_rows_checked']==2282
    findings=[
        {'id':'funding_exit_coverage','status':'fixed_and_synthetic_verified','finding':'Scheduled/gap open exits previously bypassed held funding coverage audit. Every cost branch now invalidates missing coverage before such exit.'},
        {'id':'funding_stress','status':'fixed_and_synthetic_and_real_verified','finding':'Intraminute stress previously omitted current-minute funding. Actual signed charges and ambiguity convention now included; actual stress rebuilt independently.'},
        {'id':'ema_supplement_scope','status':'fixed_with_superseded_attempt_retained','finding':'EMA initially read four settlement-only post-pool files. Uses Phase2 normalized feature source now. Correctness change, not performance selection.'},
        {'id':'symbol_contract_shards','status':'fixed_and_full_rank_and_all60_verified','finding':'Hourly artifact filename is spot symbol, not mapped contract. Three 1000-unit mappings were silently missing. All 60 now validated; 2282 rather than 2221 event candidates.'},
        {'id':'known_quarantine_rank','status':'fixed_and_independent_rank_rebuilt','finding':'A known quarantined asset still occupied eight top3 slots. Remove only at hourly timestamps >= known_ts before ranking; one legal replacement. No retroactive exclusion before knowledge.'},
        {'id':'exposure_metadata','status':'append_correction_retained','finding':'The second-attempt freeze false outcome-seen field was too broad. Its appended correction and final freeze explicitly disclose exposure to superseded outcomes.'}]
    summary={'completed_utc':datetime.now(timezone.utc).isoformat(),
        'implementation_audit_passed_with_scope_limits':True,
        'performance_goal_achieved':False,'selected_feature_groups':inc['selected_groups'],
        'enhanced_candidates_run':report['enhanced_candidates_run'],
        'synthetic_method_checks':len(syn['checks']),'synthetic_execution_checks':len(exe['checks']),
        'real_checks':{'groups_masks_scalers_FE_coefficients_and_bootstrap':6,
            'label_samples_three_horizons':inc['actual_label_samples'],'label_error_max_bp':inc['actual_label_max_abs_error_bp'],
            'known_time_event_candidates':sig['candidate_rows_checked'],'hour_ranks_rebuilt':sig['rank_rows_independently_reconstructed'],
            'all_mapped_symbols':sig['mapped_symbols_in_hourly_and_ema_and_correlation'],
            'structural_stop_samples':sig['structural_stop_and_signal_close_samples'],
            'ema_prefix_checks':len(sig['EMA_prefix_checks']),
            'trade_ledgers':ledger['total_trade_ledger_checks'],'funding_source_records':ledger['total_funding_source_checks'],
            'full_minute_equity_rows':sum(s['calendar_minutes'] for s in ledger['scenarios']),
            'maximum_equity_error_usdt':max(s['curve_max_abs_error_usdt'] for s in ledger['scenarios'])},
        'findings_and_corrections':findings,'unresolved_implementation_findings_in_audited_scope':[],
        'not_established':['Unseen future statistical confirmation','Profitable incremental feature or enhanced strategy',
            'Continuously operating drawdown below15% without permanent shutdown','Validated annualized capability from300 days',
            'Actual user VIP/historical fees, measured orderbook slippage, live latency/tick-step/liquidation behavior'],
        'risk_interpretation':'Permanent 8% stop and full cash calendar remain. Passing a15% historical drawdown threshold alone is not strategy success.',
        'research_boundary':'All history was previously explored. Jan-Mar fit, Apr-Jun selection, Jul-Apr retrospective account check; formal future90+90 not activated.',
        'no_parameter_search':'Four classes of implementation/input corrections applied uniformly with old attempts retained. Superseded returns were seen and transparently disclosed; thresholds/windows/features/selection unchanged.',
        'preservation':{'provided_by':'root independent verification','integrity_file':'../integrity_validation.json',
            'protection_file':'../protection_validation.json','phase2_frozen_files_checked':integrity['phase2_frozen_files_checked'],
            'old_source_config_metadata_files_checked':protection['files_checked'],'unchanged':True,'paper_database_accessed':False},
        'versions':{'root_protocol_sha256':sha(P3/'protocol.json'),'market_manifest_sha256':sha(ACC/'market_manifest.json'),
            'incremental_methods_sha256':sha(P3/'incremental/methods.py'),'engine_sha256':sha(ACC/'engine.py'),
            'account_market_sha256':sha(ACC/'account_market.py'),'execution_freeze_sha256':sha(ACC/'execution_freeze.json')},
        'scenario_audit':ledger['scenarios']}
    (ROOT/'audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['第三阶段独立审计结论','',
        '结论：最终修复版在本次审计范围内通过实现、因果时点、同样本和会计核对；绩效目标未实现。这两项结论不能混为一谈。',
        '六组预注册主检验均未达到Holm六检验门槛，未生成或运行增强候选；仅按原规则回放共同成熟事件基准的五种成本场景。',
        '', '已完成的核验：',
        f'1. 独立重建六组训练/筛选ID、median/IQR、币固定效应、OLS系数、币日等权loss、2000次七日块bootstrap和Holm；84个实际长短样本的15/30/60分钟标签手算误差0。',
        '2. 训练决策、已知特征与最长60分钟标签全部严格早于边界；另有6项纯合成方法检查，包含未来扰动、未知币FE、65分钟purge。',
        f'3. 全部{sig["candidate_rows_checked"]}个事件候选时点/来源身份、{sig["rank_rows_independently_reconstructed"]}个小时排名独立重建；60个映射币均覆盖小时/EMA/相关性，134个止损样本和18个EMA历史前缀一致。',
        f'4. 五场景共{ledger["total_trade_ledger_checks"]}笔交易、{ledger["total_funding_source_checks"]}笔资金费核对归档来源、价格/费用/滑点/数量/符号/边界及退出优先级；2,160,000个分钟权益与stress从独立现金流重建。最大权益误差{summary["real_checks"]["maximum_equity_error_usdt"]:.3g} USDT。',
        '5. 5项独立执行合成检查：多空同bar止损优先、跳空开盘退出、退出分钟资金费覆盖、资金费符号/边界、同bar资金费stress及未来扰动前缀。',
        '', '审计发现与修正均保留记录：资金费开盘退出覆盖、资金费stress、EMA误用结算补档、三类1000合约小时文件按错名称漏币、已知隔离币仍占排名槽。账户旧attempt均归档；曝露旧结果的事实已在追加更正及最终freeze披露。修复按来源和原规则进行，未据收益调整阈值、窗口、因子或筛选门槛。',
        '', '最终五场景（全300天）：']
    for s in ledger['scenarios']:
        lines.append(f'- {s["scenario"]}：净收益{s["net_return_pct"]:.6f}%，收盘最大回撤{s["max_drawdown_pct"]:.6f}%，交易{s["trades"]}笔。')
    lines += ['', '边界：全部是已被研究过的历史，不能称干净样本外；300天不报已验证年化。8%永久停机后保持现金，不能用约8%回撤声称持续运行风险已达标。手续费仍为固定公开档位假设，滑点为估计；未验证真实账户VIP费率、盘口、交易所历史过滤器、实盘延迟或杠杆清算。',
        f'原模拟保护：根代理独立核验Phase2 {integrity["phase2_frozen_files_checked"]}个冻结文件与{protection["files_checked"]}个旧源码/配置/metadata均未变，未打开模拟数据库；对应证据为integrity_validation.json和protection_validation.json。',
        '', '未解决的实现缺陷：本次已审计范围内无。有限合成与实际重建不构成所有可能执行路径的数学证明。']
    (ROOT/'审计结论.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'implementation_audit_passed':True,'performance_goal_achieved':False,'trade_checks':ledger['total_trade_ledger_checks'],'funding_checks':ledger['total_funding_source_checks'],'files':['audit_summary.json','审计结论.txt']},ensure_ascii=True))

if __name__=='__main__':main()
