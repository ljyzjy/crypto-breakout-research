"""Compare first-breakout 1s vs 5s confirmation without assuming paired trades."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def summary(items,unknown):
    vals=np.array([float(r['net_per_unit_notional']) for r in items]);assert np.isfinite(vals).all();n=len(vals);w=int((vals>0).sum());loss=-float(vals[vals<0].sum())
    dates={pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').date() for r in items}
    return {'trades':n,'wins':w,'net_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(vals.mean()) if n else None,
            'profit_factor':float(vals[vals>0].sum())/loss if loss else None,'active_days_utc':len(dates),
            'unknown':unknown,'optimistic_unit_win_upper_pct':100*(w+unknown)/(n+unknown) if n+unknown else None}
def main(year):
    I=H/f'{year}冻结输入';B=H/f'{year}一秒观察分批';signal=pd.read_parquet(B/'动态池逐笔信号筛查.parquet')
    oldsignal=pd.read_parquet(I/'baseline_signal.parquet');oldledger=pd.read_parquet(I/'baseline_ledger.parquet')
    ledger_path=B/'动态池单位收益与风险.parquet';ledger=pd.read_parquet(ledger_path) if ledger_path.exists() else pd.DataFrame()
    baseline=[x for x in json.loads((I/'baseline_summary.json').read_text(encoding='utf-8'))['rows'] if x['year']==year and x['strategy']=='baseline']
    assert len(signal)==len(oldsignal) and signal.observation_id.is_unique and oldsignal.observation_id.is_unique
    assert set(signal.observation_id)==set(oldsignal.observation_id)
    rows=[];details=[]
    for lev in (10,20):
        ref=next(x for x in baseline if x['leverage']==lev);v=f'one_observation_2r_{lev}x'
        index=ledger[ledger.variant.eq(v)].set_index('observation_id') if len(ledger) else pd.DataFrame()
        old=oldledger[oldledger.variant.eq(f'normal_2r_{lev}x')].set_index('observation_id')
        chosen=[];unknown=[];noorder_ids=set()
        for r in signal.to_dict('records'):
            obs=r['observation_id'];status=r['status']
            if status not in BENIGN:unknown.append(obs);continue
            if status!='qualified':noorder_ids.add(obs);continue
            pre=r[f'precheck_{lev}x']
            if pd.isna(pre):unknown.append(obs);continue
            if pre!='passed':noorder_ids.add(obs);continue
            if obs not in index.index:unknown.append(obs);continue
            record=index.loc[obs]
            if record['risk_status']!='verified' or bool(record['liq_proxy']):unknown.append(obs);continue
            item=record.to_dict();item['observation_id']=obs;chosen.append(item)
            details.append({'observation_id':obs,'leverage':lev,'entry_ts':int(item['entry_ts']),
                            'net_per_unit_notional':float(item['net_per_unit_notional']),'reason':item['reason']})
        assert len(chosen)+len(unknown)+len(noorder_ids)==len(signal)
        oldids=set(old[(old.risk_status.eq('verified'))&(~old.liq_proxy.fillna(True))].index)
        assert len(oldids)==ref['verified_events']
        oldnoorder=set();oldunknown=set();oldqualified=set()
        for oldrow in oldsignal.to_dict('records'):
            obs=oldrow['observation_id'];status=oldrow['status']
            if status not in BENIGN:oldunknown.add(obs);continue
            if status!='qualified':oldnoorder.add(obs);continue
            pre=oldrow[f'precheck_{lev}x']
            if pd.isna(pre):oldunknown.add(obs);continue
            if pre!='passed':oldnoorder.add(obs);continue
            if obs in oldids:oldqualified.add(obs)
            else:oldunknown.add(obs)
        assert oldqualified==oldids and len(oldnoorder)==ref['known_no_order'] and len(oldunknown)==ref['possible_unknown_events']
        newids={x['observation_id'] for x in chosen};common=oldids&newids
        rows.append({'leverage':lev,'candidate_events':len(signal),'known_no_order':len(noorder_ids),
            'one_second_observation':summary(chosen,len(unknown)),
            'five_second_observation_baseline':{'trades':ref['verified_events'],'wins':ref['verified_wins'],
                'net_win_rate_pct':ref['verified_win_rate_pct'],'mean_net_pct_notional':ref['mean_net_pct_notional'],
                'profit_factor':ref['profit_factor'],'active_days_utc':ref['verified_active_days_utc'],
                'unknown':ref['possible_unknown_events'],'optimistic_unit_win_upper_pct':ref['unit_win_rate_upper_pct']},
            'common_known_entries':len(common),'new_entries_where_baseline_known_no_order':len(newids&oldnoorder),
            'new_entries_where_baseline_unknown':len(newids&oldunknown),'baseline_entries_where_new_known_no_order':len(oldids&noorder_ids),
            'baseline_entries_where_new_unknown':len(oldids&set(unknown)),
            'unknown_ids':sorted(unknown)})
    pd.DataFrame(details).to_parquet(H/f'{year}一秒观察已核验机会.parquet',index=False)
    out={'year':year,'rows':rows,'note':'First-breakout only, different trade sets; unit opportunities, no account or actual fills.'}
    (H/f'{year}一秒观察对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_RESULTS',year,json.dumps({'rows':[{k:v for k,v in r.items() if k!='unknown_ids'} for r in rows]},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
