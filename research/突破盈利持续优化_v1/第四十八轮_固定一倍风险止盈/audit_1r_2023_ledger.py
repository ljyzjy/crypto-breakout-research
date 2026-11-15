"""Recompute 1R execution costs, mark-risk and paired summary independently."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;I=H/'2023冻结输入';B=H/'2023一倍止盈分批';M=60_000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    assert json.loads((H/'2023一倍止盈逐笔独立抽查.json').read_text(encoding='utf-8'))['all_checks_pass']
    manifest=json.loads((B/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    expected={(x['kind'],x['contract'],x['month']):x for x in manifest};matched=set();marks={};funds={}
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_old11_2023_serialv1'
    for file in cache.glob('*.json'):
        z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month'])
        if key not in expected or expected[key].get('sha256')!=z.get('sha256'):continue
        matched.add(key)
        if z['kind']=='markPriceKlines':
            for x in z['rows']:marks[(z['contract'],int(x['ts']))]=x
        else:funds[(z['contract'],z['month'])]=z['rows']
    assert len(matched)==sum(x['status']=='verified' for x in manifest)
    ledger=pd.read_parquet(B/'动态池单位收益与风险.parquet');checked=0;maxerr=0.
    for r in ledger.itertuples(index=False):
        if r.risk_status!='verified':continue
        side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005);qty=1/entry
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill) and r.entry_ts>=r.decision_ts+10000 and r.exit_ts>=r.exit_signal_ts+5000
        funding=0.;actual_events=[];extremes=[]
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            mark=marks[(r.contract,ts)];extremes.append(float(mark['low'] if side==1 else mark['high']))
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            for x in funds.get((r.contract,month),[]):
                ft=int(x['ts'])
                if ft//M*M!=ts or not r.entry_ts<=ft<=r.exit_ts:continue
                amount=side*qty*float(mark['open'])*float(x['last_funding_rate'])
                funding+=max(0.,amount) if ft in (r.entry_ts,r.exit_ts) else amount;actual_events.append(ft)
        assert near(funding,r.funding) and sorted(actual_events)==sorted(int(x['settlement_ts']) for x in json.loads(r.funding_events_json))
        net=side*qty*(exit-entry)-.0005-qty*exit*.0005-funding
        assert near(net,r.net_per_unit_notional) and near(r.entry_fee,.0005) and near(r.exit_fee,qty*exit*.0005)
        lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
        assert any(1/lev-.0005-max(funding,0.)+side*qty*(v-entry)<=qty*v*.01 for v in extremes)==bool(r.liq_proxy)
        maxerr=max(maxerr,abs(net-r.net_per_unit_notional));checked+=1
    detail=pd.read_parquet(H/'2023一倍两倍逐笔配对结果.parquet');result=json.loads((H/'2023一倍两倍配对对照.json').read_text(encoding='utf-8'))
    old=pd.concat([pd.read_parquet(I/'baseline_ledger.parquet'),pd.read_parquet(I/'retry_ledger.parquet')],ignore_index=True)
    for row in result['rows']:
        lev=row['leverage'];a=old[old.variant.eq(f'normal_2r_{lev}x')];b=ledger[ledger.variant.eq(f'normal_1r_{lev}x')]
        a=a[a.risk_status.eq('verified')&~a.liq_proxy.fillna(True)].set_index('observation_id')
        b=b[b.risk_status.eq('verified')&~b.liq_proxy.fillna(True)].set_index('observation_id')
        ids=set(a.index)&set(b.index);d=detail[detail.leverage.eq(lev)].set_index('observation_id')
        assert set(d.index)==ids and len(ids)==row['paired_verified']
        for obs in ids:
            assert near(d.loc[obs,'one_r_net'],b.loc[obs,'net_per_unit_notional']) and near(d.loc[obs,'two_r_net'],a.loc[obs,'net_per_unit_notional'])
        for name,col in (('one_r','one_r_net'),('two_r','two_r_net')):
            values=d[col].astype(float);win=int((values>0).sum());n=len(values)
            assert row[name]['trades']==n and row[name]['wins']==win
            if n:assert near(row[name]['net_win_rate_pct'],100*win/n) and near(row[name]['mean_net_pct_notional'],100*values.mean())
        assert row['candidate_events']==row['known_no_order']+row['paired_unknown']+row['paired_verified']
        if len(d):assert near(row['mean_1r_minus_2r_pct_notional'],100*(d.one_r_net-d.two_r_net).mean())
    out={'all_checks_pass':True,'audited_1r_ledger_paths':checked,'matched_risk_archives':len(matched),
         'maximum_net_fraction_error':maxerr,'note':'Known paired opportunities only; account-level outcomes were not simulated.'}
    (H/'2023一倍止盈账本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2023_LEDGER_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
