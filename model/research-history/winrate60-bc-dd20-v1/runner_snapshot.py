"""User-directed single change: account permanent halt from8% to20%."""
from common import *
import importlib.util, difflib, copy
from datetime import datetime,timezone

replay_spec=importlib.util.spec_from_file_location('win60_replay',Path(__file__).with_name('run_accounts.py'))
replay=importlib.util.module_from_spec(replay_spec);replay_spec.loader.exec_module(replay)

NEW=BASE/'outputs/winrate60-bc-dd20-v1'
def main():
    NEW.mkdir(parents=True,exist_ok=True)
    assert not (NEW/'registration.json').exists(), 'Never overwrite a frozen experiment'
    frozen=read(OUT/'models/FROZEN.json')
    assert sha(OUT/'predictions/all.parquet')==frozen['prediction_sha256']
    for name,expected in frozen['models'].items():assert sha(OUT/'models'/name)==expected
    original=(P3/'account/engine.py').read_text(encoding='utf-8')
    before='if dd_known>=.08 and not permanent_pause:permanent_pause=True;pause_ts=ts'
    after='if dd_known>=.20 and not permanent_pause:permanent_pause=True;pause_ts=ts'
    assert original.count(before)==1
    changed=original.replace(before,after)
    engine_path=NEW/'engine_dd20.py';engine_path.write_text(changed,encoding='utf-8')
    (NEW/'engine_change.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),fromfile='original_engine.py',tofile='engine_dd20.py')),encoding='utf-8')
    protocol=copy.deepcopy(PROTOCOL)
    protocol.update(id='winrate60-bc-dd20-v1',registered_utc=datetime.now(timezone.utc).isoformat(),
      new_B_C_outcomes_seen=True,parent_protocol_sha256=sha(OUT/'protocol.json'),
      change='User-directed permanent account drawdown halt8% ->20%, only execution rule change.',
      acceptance_max_drawdown_pct=15,permanent_halt_drawdown_pct=20,
      new_models_trained=False,current_paper_changed=False,
      evaluation='Same300days, frozen signals/models, A/B/C allfivecosts; compare previous8% results.')
    protocol['account']['protection']=protocol['account']['protection'].replace('peakDD8%','peakDD20%')
    dump(NEW/'protocol.json',protocol)
    protected=read(OUT/'registration.json')['protected_files'].copy()
    for rel,item in read(P3/'protected_before.json')['files'].items():protected[str((BASE/rel).resolve())]=item['sha256']
    for rel,item in read(OUT/'deliverable_manifest.json')['files'].items():protected[str((OUT/rel).resolve())]=item['sha256']
    dump(NEW/'registration.json',{'utc':protocol['registered_utc'],'protocol_sha256':sha(NEW/'protocol.json'),
      'original_engine_sha256':sha(P3/'account/engine.py'),'new_engine_sha256':sha(engine_path),
      'runner_sha256':sha(Path(__file__)),'old_model_freeze_sha256':sha(OUT/'models/FROZEN.json'),
      'protected_files':protected,'user_requested_single_threshold_change':True,'new20pct_outcomes_seen':False})
    spec=importlib.util.spec_from_file_location('isolated_dd20_engine',engine_path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    replay.OUT=NEW;replay.simulate=engine.simulate
    pred=pd.read_parquet(OUT/'predictions/all.parquet');baseline=pd.read_parquet(P3/'account/event-signals.parquet');guard=RankTrendGuard();results=[]
    for variant in ['A','B','C']:
        signals=baseline if variant=='A' else pred[pred.variant.eq(variant)&pred.split.eq('evaluation')&pred.filter_pass].copy()
        for scenario in PROTOCOL['cost_scenarios']:
            result=replay.run_one(variant,scenario,signals,guard)
            result['permanent_halt_drawdown_pct']=20;result['acceptance_max_drawdown_pct']=15
            dump(NEW/f"accounts/{variant}/{scenario['id']}-summary.json",result);results.append(result)
    dump(NEW/'account_results.json',{'results':results,'halt_threshold_pct':20,'acceptance_drawdown_pct':15,'retrained_models':False,'paper_changed':False})
    checks=[];comparisons=[]
    for r in results:
        v=r['run_id'];sc=r['scenario'];new=pd.read_parquet(NEW/f'accounts/{v}/{sc}-curve.parquet')
        if v=='A':
            old=read(P3/f'account/results/event_baseline/{sc}-summary.json');oldcurve=pd.read_parquet(P3/f'account/results/event_baseline/{sc}-curve.parquet')
        else:
            old=read(OUT/f'accounts/{v}/{sc}-summary.json');oldcurve=pd.read_parquet(OUT/f'accounts/{v}/{sc}-curve.parquet')
        boundary=old['permanent_pause_ts']
        oldprefix=oldcurve if boundary is None else oldcurve[oldcurve.ts.le(boundary)]
        newprefix=new[new.ts.isin(oldprefix.ts)]
        pd.testing.assert_frame_equal(oldprefix[['ts','equity','drawdown','exposure','positions']].reset_index(drop=True),newprefix[['ts','equity','drawdown','exposure','positions']].reset_index(drop=True),check_exact=True)
        halt=r['permanent_pause_ts']
        if halt is not None:
            known=new[new.ts.eq(halt)].iloc[0]
            assert known.drawdown>=20
            assert new.loc[new.ts.lt(halt),'drawdown'].lt(20).all()
        assert r['observed_calendar_minutes']==432000 and r['valid_for_comparison']
        trades=read(NEW/f'accounts/{v}/{sc}-trades.json');entries=read(NEW/f'accounts/{v}/{sc}-entries.json')
        assert all(e['feature_known_ts']<=e['decision_ts']<e['ts'] for e in entries)
        if v!='A':assert r['trades']==0 and r['net_pnl']==0 and len(trades)==0
        checks.append({'variant':v,'scenario':sc,'identical_before_old_halt':True,'old_prefix_minutes':len(oldprefix),'new_halt_threshold_verified':halt is not None,'full_calendar':True,'ledger_error':r['net_ledger_error']})
        comparisons.append({'variant':v,'scenario':sc,'old_trades':old['trades'],'new_trades':r['trades'],
          'old_win_rate_pct':old['win_rate'] if old['trades'] else None,'new_win_rate_pct':r['net_win_rate_pct'],
          'old_return_pct':old['return_pct'],'new_return_pct':r['return_pct'],'new_net_pnl':r['net_pnl'],
          'old_drawdown_pct':old['max_drawdown'],'new_drawdown_pct':r['max_drawdown'],'new_stress_drawdown_pct':r['intrabar_stress_dd'],
          'active_days':r['active_calendar_days'],'old_halt_ts':old['permanent_pause_ts'],'new_halt_ts':halt,
          'acceptance_pass':r['acceptance_pass']})
    source_changes=[p for p,want in protected.items() if not Path(p).is_file() or sha(p)!=want]
    assert not source_changes,source_changes
    assert engine_path.read_text(encoding='utf-8').replace(after,before)==original
    dump(NEW/'audit.json',{'utc':datetime.now(timezone.utc).isoformat(),'passed':True,'source_files_checked':len(protected),'source_changes':source_changes,'single_execution_line_change':True,'all_scenarios':checks,'models_and_predictions_unchanged':True,'paper_database_accessed':False,'no_future_feature_change':True})
    pd.DataFrame(comparisons).to_csv(NEW/'8与20停机阈值比较.csv',index=False,encoding='utf-8-sig')
    dump(NEW/'comparison.json',comparisons)
    mainrow=next(r for r in results if r['run_id']=='A' and r['scenario']=='main')
    old=read(OUT/'accounts/A/main-summary.json')
    date=lambda t:pd.Timestamp(t,unit='ms',tz='UTC').tz_convert('Asia/Shanghai').strftime('%Y-%m-%d %H:%M') if t else '未触发'
    rows='\n'.join(f"|{c['scenario']}|{c['new_trades']}|{c['new_win_rate_pct']:.2f}%|{c['new_return_pct']:.2f}%|{c['new_drawdown_pct']:.2f}%|{date(c['new_halt_ts'])}|" for c in comparisons if c['variant']=='A')
    report=f'''# 账户永久停机阈值8%改为20%的回放结果

按用户要求，仅把研究回放中的账户峰值回撤永久停机阈值由8%改为20%。原5%回撤减半风险、日亏损1.5%暂停、模型、65%概率门槛、成本、仓位、2R止盈、60分钟期限均保留。15%最大回撤验收标准未更改。现有模拟未改动，未访问其数据库。

统一评估期：2025-07-01至2026-04-26，共300天，起始1000 USDT，1×敞口上限。沿用原60个映射永续合约历史池、训练及校准结果。没有重新训练、没有搜索其它停机阈值。

|主成本结果|原8%停机|新20%停机|
|---|---:|---:|
|A实际交易|{old['trades']}|{mainrow['trades']}|
|A净胜率|{old['net_win_rate_pct']:.2f}%|{mainrow['net_win_rate_pct']:.2f}%|
|A净利润|{old['net_pnl']:.2f} USDT|{mainrow['net_pnl']:.2f} USDT|
|A总收益|{old['return_pct']:.2f}%|{mainrow['return_pct']:.2f}%|
|A最大回撤|{old['max_drawdown']:.2f}%|{mainrow['max_drawdown']:.2f}%|
|A活跃交易日|{old['active_calendar_days']}|{mainrow['active_calendar_days']}|
|A永久停机时间（北京时间）|{date(old['permanent_pause_ts'])}|{date(mainrow['permanent_pause_ts'])}|

B、C的模型和预测文件完全复用。固定65%概率及正净期望门槛仍无合格信号，两个版本在全部五种成本下依旧0笔交易、0净收益、0回撤，净胜率不可计算，不视为成功。

## A的五种成本回放

|成本场景|交易数|净胜率|总收益|最大回撤|停机时间（北京时间）|
|---|---:|---:|---:|---:|---|
{rows}

main：单边手续费0.05%、不利滑点0.05%，另计历史资金费；fee2/fee3：手续费两倍/三倍；slip2：滑点两倍；delay1：额外延迟一分钟。费率沿用既有回测假设，滑点为估计。

20%是触发停机的阈值，不是硬性保证实际最大回撤不超过20%；分钟成交、费用及下一分钟平仓可能使回撤略超过阈值。15%的验收要求独立保留，因此即使在20%附近停机，也不满足15%回撤目标。

## 检查

- 已完成A/B/C各五种成本场景，共15次432,000分钟的完整回放。
- 所有场景在原8%停机触发前，与原账户逐分钟净值、回撤、敞口、持仓数量完全一致。
- 每个实际触发20%停机的场景均核验首次可知回撤达到20%的时间。
- 所有交易与资金费账对平，入场时间晚于特征可知时间。
- {len(protected)}个旧文件哈希核对未变；模型与预测未重算。
- 既有8%版本、结果及协议保留，新版本隔离保存。

这是用户指定的单一风控改动检验，不能将增加交易数量解释为信号识别改善。历史仍为此前已研究的回顾性样本。
'''
    (NEW/'20停机阈值回测报告.md').write_text(report,encoding='utf-8')
    (NEW/'runner_snapshot.py').write_bytes(Path(__file__).read_bytes())
    dump(NEW/'deliverable_manifest.json',{'utc':datetime.now(timezone.utc).isoformat(),'files':{p.relative_to(NEW).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in NEW.rglob('*') if p.is_file() and p.name!='deliverable_manifest.json'},'audit_passed':True})
    print('DD20_COMPLETE',json.dumps({k:mainrow[k] for k in ['trades','net_win_rate_pct','net_pnl','return_pct','max_drawdown','permanent_pause_ts']}),flush=True)

if __name__=='__main__':main()
