"""Classify every frozen candidate and score risk-audited raw-trade paths."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent;B=H/'原始逐笔批次';R93=H.parent/'第九十三轮_原始逐笔抽样交叉核验';D=Decimal
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}


def metric(trades,slip):
    values=[]
    for r in trades:
        side=D(r['side']);fill=D(r['entry_fill']);raw=D(r['exit_raw']);funding=D(r['funding']);ex=raw*(1-side*slip)
        values.append(side*(ex-fill)/fill-D('.0005')-D('.0005')*ex/fill-funding)
    wins=[x for x in values if x>0]; losses=[x for x in values if x<0]
    return {'trades':len(values),'net_wins':len(wins),'net_win_rate_pct':float(D(100)*len(wins)/len(values)) if values else None,
            'mean_net_pct_notional':float(D(100)*sum(values)/len(values)) if values else None,
            'profit_factor':float(sum(wins)/-sum(losses)) if losses else None,
            'active_utc_days':len({pd.Timestamp(int(x['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for x in trades})}


def main():
    bulk.runner.guard(start=True); bulk.frozen(); tape=json.loads((H/'原始逐笔独立抽样核验.json').read_text(encoding='utf-8'))
    risk=json.loads((H/'风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    assert tape['all_checks_pass'] and tape['fingerprint']==bulk.fingerprint() and tape['code_sha256']==bulk.sha(H/'audit_tapes.py')
    assert risk['all_checks_pass'] and risk['code_sha256']==bulk.sha(H/'audit_risk.py') and risk['ledger_sha256']==bulk.sha(B/'单位净收益与风险.parquet')
    signals=pd.read_parquet(B/'逐笔信号.parquet');paths=pd.read_parquet(B/'模拟路径.parquet');ledger=pd.read_parquet(B/'单位净收益与风险.parquet')
    assert len(signals)==310 and signals.observation_id.is_unique
    bypath={(r['observation_id'],r['variant']):r for r in paths.to_dict('records')}
    byledger={(r['observation_id'],r['variant']):r for r in ledger.to_dict('records')}
    assert len(bypath)==len(paths) and len(byledger)==len(ledger)
    all_details=[]; summaries=[]
    for lev in (10,20):
        variant=f'one_observation_2r_{lev}x';trades=[];unknown=0;no_order=0
        for s in signals.to_dict('records'):
            key=(s['observation_id'],variant);r=byledger.get(key);p=bypath.get(key)
            item={'observation_id':key[0],'leverage':lev,'signal_status':s['status'],'category':'','reason':''}
            if s['status'] not in BENIGN: item.update(category='unknown',reason=s['status']);unknown+=1
            elif s['status']!='qualified': item.update(category='no_order',reason=s['status']);no_order+=1
            elif pd.isna(s[f'precheck_{lev}x']): item.update(category='unknown',reason='missing_precheck');unknown+=1
            elif s[f'precheck_{lev}x']!='passed':item.update(category='no_order',reason=s[f'precheck_{lev}x']);no_order+=1
            elif not p or p['status']!='verified':item.update(category='unknown',reason='missing_or_unverified_path');unknown+=1
            elif not r or r['risk_status']!='verified':item.update(category='unknown',reason='missing_or_unverified_risk');unknown+=1
            elif bool(r['liq_proxy']):item.update(category='unknown',reason='liquidation_proxy');unknown+=1
            else:
                assert int(r['entry_signal_reference_ts'])>=int(r['decision_ts'])+1000 and int(r['entry_ts'])>=int(r['entry_signal_reference_ts'])+1000
                assert int(r['exit_ts'])>=int(r['exit_signal_ts'])+5000
                side=D(int(r['side']));fill=D(str(r['entry_fill']));raw=D(str(r['exit_raw']));funding=D(str(r['funding']));ex=raw*(1-side*D('.0005'))
                net=side*(ex-fill)/fill-D('.0005')-D('.0005')*ex/fill-funding
                assert abs(net-D(str(r['net_per_unit_notional'])))<D('1e-11')
                trade={'entry_ts':int(r['entry_ts']),'entry_fill':str(fill),'exit_raw':str(raw),'side':str(side),'funding':str(funding),'net':str(net)}
                trades.append(trade);item.update(category='trade',reason=r['reason'],**trade)
            all_details.append(item)
        assert len(trades)+unknown+no_order==len(signals)
        for slip in (D('.0005'),D('.00075'),D('.001')):
            summaries.append({'leverage':lev,'exit_slippage_pct':float(slip*100),**metric(trades,slip),'known_no_order':no_order,'unknown_candidates':unknown})
    cols=['observation_id','leverage','signal_status','category','reason','entry_ts','entry_fill','exit_raw','side','funding','net']
    with (H/'候选状态与单位账本.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(all_details)
    baseline=pd.read_csv(bulk.R90/'二零二二候选状态及单位账本.csv',dtype=str,keep_default_na=False)
    affected=set(json.loads((R93/'原始数据分歧敏感性.json').read_text(encoding='utf-8'))['affected_observation_ids'])
    pairs=[]
    for lev in (10,20):
        a=baseline[(baseline.holding_rule=='original')&(baseline.leverage==str(lev))&(baseline.cohort=='base')].copy()
        a.loc[a.observation_id.isin(affected),'category']='unknown'
        b=pd.DataFrame([x for x in all_details if x['leverage']==lev]);joined=a.merge(b,on='observation_id',suffixes=('_agg','_raw'),validate='one_to_one')
        pairs.append({'leverage':lev,'categories':joined.groupby(['category_agg','category_raw']).size().reset_index(name='n').to_dict('records'),
                      'common_trades':int(((joined.category_agg=='trade')&(joined.category_raw=='trade')).sum())})
    out={'rows':summaries,'paired_categories':pairs,'candidate_count':len(signals),'unknown_rank_hours_original':240,
         'detail_sha256':bulk.sha(H/'候选状态与单位账本.csv'),'tape_audit_sha256':bulk.sha(H/'原始逐笔独立抽样核验.json'),
         'risk_audit_sha256':bulk.sha(H/'风险来源与账本独立核验.json'),'code_sha256':bulk.sha(Path(__file__)),
         'note':'Retrospective raw-count variation; fixed slippage only; incomplete ranked hours and no account-equity drawdown.'}
    (H/'原始逐笔汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT98_SUMMARY',json.dumps(summaries,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
