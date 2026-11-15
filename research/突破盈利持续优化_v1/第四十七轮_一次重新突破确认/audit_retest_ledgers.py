"""Independently reconcile retry risk, costs, missingness and paired summaries."""
import json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60_000
ORIG={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def read(p):return pd.read_parquet(p) if p.exists() else pd.DataFrame()
def main():
    assert json.loads((H/'重试逐笔独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    single='--2023-only' in sys.argv
    result=json.loads((H/('2023单次重试单位对照.json' if single else '单次重试跨期单位对照.json')).read_text(encoding='utf-8'));audited=0;maxerror=0.;groups=[]
    for year in (('2023',) if single else ('2023','2024','2026')):
        inp=H/('2023冻结输入' if year=='2023' else '跨期冻结输入');d=H/f'{year}重试分批'
        base=read(inp/('baseline_signal.parquet' if year=='2023' else f'{year}_signal.parquet'))
        bp=read(inp/('baseline_paths.parquet' if year=='2023' else f'{year}_paths.parquet'))
        bl=read(inp/('baseline_ledger.parquet' if year=='2023' else f'{year}_ledger.parquet'))
        rs=read(d/'动态池逐笔信号筛查.parquet');rp=read(d/'动态池延迟市价路径.parquet');rl=read(d/'动态池单位收益与风险.parquet')
        if len(rl):
            manifest=json.loads((d/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
            cache=ROOT/'work'/'point_in_time_universe33'/('risk_old11_2023_serialv1' if year=='2023' else 'risk_fixed11_cross46')
            expected={(x['kind'],x['contract'],x['month']):x for x in manifest};marks={};funds={};matched=set()
            for file in cache.glob('*.json'):
                z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month'])
                if key not in expected or expected[key].get('sha256')!=z['sha256']:continue
                matched.add(key)
                if z['kind']=='markPriceKlines':
                    for x in z['rows']:marks[(z['contract'],int(x['ts']))]=x
                else:funds[(z['contract'],z['month'])]=z['rows']
            assert len(matched)==sum(x['status']=='verified' for x in manifest)
            for r in rl.itertuples(index=False):
                if r.risk_status!='verified':continue
                side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005);qty=1/entry
                assert near(entry,r.entry_fill) and near(exit,r.exit_fill) and r.entry_ts>=r.decision_ts+10_000 and r.exit_ts>=r.exit_signal_ts+5_000
                pay=0.;events=[];adverse=[]
                for t in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
                    bar=marks[(r.contract,t)];adverse.append(float(bar['low'] if side==1 else bar['high']))
                    month=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m')
                    for x in funds.get((r.contract,month),[]):
                        ft=int(x['ts'])
                        if ft//M*M!=t or not r.entry_ts<=ft<=r.exit_ts:continue
                        charge=side*qty*float(bar['open'])*float(x['last_funding_rate'])
                        pay+=max(0.,charge) if ft in (r.entry_ts,r.exit_ts) else charge;events.append(ft)
                assert near(pay,r.funding) and sorted(events)==sorted(int(x['settlement_ts']) for x in json.loads(r.funding_events_json))
                net=side*qty*(exit-entry)-.0005-qty*exit*.0005-pay
                assert near(r.entry_fee,.0005) and near(r.exit_fee,qty*exit*.0005) and near(net,r.net_per_unit_notional)
                maxerror=max(maxerror,abs(net-r.net_per_unit_notional));lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
                assert any(1/lev-.0005-max(pay,0.)+side*qty*(v-entry)<=qty*v*.01 for v in adverse)==bool(r.liq_proxy)
                audited+=1
        retry={x['observation_id']:x for x in rs.to_dict('records')};assert len(retry)==len(rs)
        for lev in (10,20):
            variant=f'normal_2r_{lev}x'
            def index(x):return {r['observation_id']:r for r in x[x.variant.eq(variant)].to_dict('records')} if len(x) else {}
            original_paths,original_ledgers,retry_paths,retry_ledgers=index(bp),index(bl),index(rp),index(rl)
            for strategy in ('baseline','single_retest'):
                good={};unknown=set();noorder=0;added=0
                for original in base.to_dict('records'):
                    obs=original['observation_id'];isnew=strategy=='single_retest' and obs in retry
                    event=retry[obs] if isnew else original;statuses=RETRY if isnew else ORIG
                    pp=(retry_paths if isnew else original_paths).get(obs);r=(retry_ledgers if isnew else original_ledgers).get(obs)
                    if event['status'] not in statuses:unknown.add(obs);continue
                    if event['status']!='qualified':noorder+=1;continue
                    pre=event[f'precheck_{lev}x']
                    if pd.isna(pre):unknown.add(obs);continue
                    if pre!='passed':noorder+=1;continue
                    if pp is None or pp['status']!='verified' or r is None or r['risk_status']!='verified' or r['liq_proxy']:unknown.add(obs);continue
                    good[obs]=r;added+=int(isnew)
                row=next(x for x in result['rows'] if x['year']==year and x['strategy']==strategy and x['leverage']==lev)
                vals=[float(x['net_per_unit_notional']) for x in good.values()];n=len(vals);u=len(unknown);w=sum(x>0 for x in vals)
                assert n+u+noorder==len(base) and set(row['verified_observation_ids'])==set(good) and set(row['unknown_observation_ids'])==unknown
                assert row['known_no_order']==noorder and row['verified_events']==n and row['verified_wins']==w and row['verified_added_retest_entries']==added
                if n:assert near(row['verified_win_rate_pct'],100*w/n) and near(row['mean_net_pct_notional'],100*sum(vals)/n)
                if n+u:assert near(row['unit_win_rate_upper_pct'],100*(w+u)/(n+u)) and near(row['unit_win_rate_lower_pct'],100*w/(n+u))
                if year=='2023':
                    labels=read(inp/'postclose_labels.parquet').set_index('observation_id');cand=read(inp/'candidates.parquet').set_index('observation_id')
                    large={i for i,x in labels.iterrows() if x.status=='verified' and bool(x.large)}
                    cap={i for i,r in good.items() if i in large and int(r['side'])==int(labels.loc[i,'allowed_side']) and int(r['entry_ts'])<int(cand.loc[i,'quarter_end'])}
                    actual=next(x for x in result['postclose_2023_capture'] if x['strategy']==strategy and x['leverage']==lev)
                    assert set(actual['captured_observation_ids'])==cap and set(actual['unknown_large_observation_ids'])==large&unknown
                groups.append({'year':year,'strategy':strategy,'leverage':lev,'verified':n,'wins':w,'unknown':u,'added':added})
    out={'independent_retry_ledger_paths':audited,'maximum_net_fraction_error':maxerror,'groups':groups,'all_checks_pass':True,
         'note':'Original and retry opportunities remain unit paths, not concurrent account fills.'}
    (H/('2023单次重试对照独立核验.json' if single else '单次重试净账本独立核验.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_LEDGER_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
