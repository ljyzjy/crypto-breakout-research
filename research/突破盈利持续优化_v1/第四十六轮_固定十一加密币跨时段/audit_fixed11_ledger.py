"""Independently recalculate fixed-pool risk, costs and outcome bounds."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60_000
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    result=json.loads((H/'固定十一币跨期单位诊断.json').read_text(encoding='utf-8'))
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46';count=0;maximum_error=0.;groups=[]
    for year in ('2024','2026'):
        d=H/year/'逐笔分批';s=pd.read_parquet(d/'动态池逐笔信号筛查.parquet').to_dict('records')
        p=pd.read_parquet(d/'动态池延迟市价路径.parquet');l=pd.read_parquet(d/'动态池单位收益与风险.parquet')
        manifest=json.loads((d/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
        expected={(x['kind'],x['contract'],x['month']):x for x in manifest};marks={};funds={};matched=set()
        for file in cache.glob('*.json'):
            z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month'])
            if key not in expected or expected[key].get('sha256')!=z['sha256']:continue
            matched.add(key)
            if z['kind']=='markPriceKlines':
                for x in z['rows']:marks[(z['contract'],int(x['ts']))]=x
            else:funds[(z['contract'],z['month'])]=z['rows']
        assert len(matched)==sum(x['status']=='verified' for x in manifest)
        for r in l.itertuples(index=False):
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
            maximum_error=max(maximum_error,abs(net-r.net_per_unit_notional));lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
            hit=any(1/lev-.0005-max(pay,0.)+side*qty*(x-entry)<=qty*x*.01 for x in adverse)
            assert hit==bool(r.liq_proxy);count+=1
        for lev in (10,20):
            v=f'normal_2r_{lev}x';paths={x['observation_id']:x for x in p[p.variant.eq(v)].to_dict('records')}
            ledgers={x['observation_id']:x for x in l[l.variant.eq(v)].to_dict('records')}
            good={};unknown=set();noorder=0
            for e in s:
                obs=e['observation_id']
                if e['status'] not in BENIGN:unknown.add(obs);continue
                if e['status']!='qualified':noorder+=1;continue
                pre=e[f'precheck_{lev}x']
                if pd.isna(pre):unknown.add(obs);continue
                if pre!='passed':noorder+=1;continue
                pp=paths.get(obs);r=ledgers.get(obs)
                if pp is None or pp['status']!='verified' or r is None or r['risk_status']!='verified' or r['liq_proxy']:unknown.add(obs);continue
                good[obs]=float(r['net_per_unit_notional'])
            row=next(x for x in result['rows'] if x['period']==year and x['leverage']==lev)
            n=len(good);u=len(unknown);w=sum(v>0 for v in good.values())
            assert n+u+noorder==len(s) and set(row['verified_observation_ids'])==set(good) and set(row['unknown_observation_ids'])==unknown
            assert row['known_no_order']==noorder and row['verified_events']==n and row['verified_wins']==w
            if n:assert near(row['verified_win_rate_pct'],100*w/n) and near(row['mean_net_pct_notional'],100*sum(good.values())/n)
            if n+u:assert near(row['unit_win_rate_upper_pct'],100*(w+u)/(n+u)) and near(row['unit_win_rate_lower_pct'],100*w/(n+u))
            groups.append({'year':year,'leverage':lev,'verified':n,'wins':w,'unknown':u,'no_order':noorder})
    out={'independently_checked_verified_paths':count,'maximum_net_fraction_error':maximum_error,'groups':groups,'all_checks_pass':True,
         'note':'Fixed-11 unit opportunities, not actual fills or account-level returns.'}
    (H/'固定十一币净账本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_LEDGER_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
