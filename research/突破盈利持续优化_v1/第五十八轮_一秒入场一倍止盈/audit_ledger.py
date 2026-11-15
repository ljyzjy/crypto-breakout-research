"""Independently recompute fees, funding, risk proxy and 1R/2R pairing."""
import json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main(year):
    I=H/f'{year}冻结输入';B=H/f'{year}一秒一倍分批'
    sample=json.loads((H/f'{year}一秒一倍逐笔独立核验.json').read_text(encoding='utf-8'));assert sample['all_checks_pass']
    manifest=json.loads((B/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    expected={(x['kind'],x['contract'],x['month']):x for x in manifest};matched=set();marks={};funds={}
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46'
    for file in cache.glob('*.json'):
        z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month'])
        if key not in expected or expected[key].get('sha256')!=z.get('sha256'):continue
        matched.add(key)
        if z['kind']=='markPriceKlines':
            for bar in z['rows']:marks[(z['contract'],int(bar['ts']))]=bar
        else:funds[(z['contract'],z['month'])]=z['rows']
    assert len(matched)==len(manifest)
    ledger=pd.read_parquet(B/'动态池单位收益与风险.parquet');old=pd.read_parquet(I/'ledger_2r.parquet')
    originals={(r.observation_id,r.variant):r for r in old.itertuples(index=False)};checked=0;maxerr=0.
    for r in ledger.itertuples(index=False):
        if r.risk_status!='verified':continue
        baseline=originals[(r.observation_id,r.variant.replace('one_second_1r_','one_second_2r_'))]
        assert int(r.entry_ts)==int(baseline.entry_ts) and int(r.exit_ts)<=int(baseline.exit_ts)
        side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005);qty=1/entry
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill) and r.entry_ts>=r.entry_signal_reference_ts+1000 and r.exit_ts>=r.exit_signal_ts+5000
        funding=0.;events=[];extremes=[]
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            mark=marks[(r.contract,ts)];extremes.append(float(mark['low'] if side==1 else mark['high']))
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            for x in funds.get((r.contract,month),[]):
                ft=int(x['ts'])
                if ft//M*M!=ts or not r.entry_ts<=ft<=r.exit_ts:continue
                amount=side*qty*float(mark['open'])*float(x['last_funding_rate'])
                funding+=max(0.,amount) if ft in (r.entry_ts,r.exit_ts) else amount;events.append(ft)
        assert near(funding,r.funding) and sorted(events)==sorted(int(x['settlement_ts']) for x in json.loads(r.funding_events_json))
        net=side*qty*(exit-entry)-.0005-qty*exit*.0005-funding
        assert near(net,r.net_per_unit_notional) and near(r.entry_fee,.0005) and near(r.exit_fee,qty*exit*.0005)
        lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
        assert any(1/lev-.0005-max(funding,0.)+side*qty*(v-entry)<=qty*v*.01 for v in extremes)==bool(r.liq_proxy)
        maxerr=max(maxerr,abs(net-r.net_per_unit_notional));checked+=1
    detail=pd.read_parquet(H/f'{year}一秒一倍两倍逐笔配对.parquet');results=json.loads((H/f'{year}一秒一倍两倍配对对照.json').read_text(encoding='utf-8'))['rows']
    for row in results:
        lev=row['leverage'];a=old[old.variant.eq(f'one_second_2r_{lev}x')].set_index('observation_id')
        b=ledger[ledger.variant.eq(f'one_second_1r_{lev}x')].set_index('observation_id')
        d=detail[detail.leverage.eq(lev)].set_index('observation_id');assert len(d)==row['paired_verified']
        for obs,x in d.iterrows():
            assert a.loc[obs,'risk_status']=='verified' and b.loc[obs,'risk_status']=='verified'
            assert not a.loc[obs,'liq_proxy'] and not b.loc[obs,'liq_proxy']
            assert near(x['two_r_net'],a.loc[obs,'net_per_unit_notional']) and near(x['one_r_net'],b.loc[obs,'net_per_unit_notional'])
        for name,col in (('one_r','one_r_net'),('two_r','two_r_net')):
            vals=d[col].astype(float);n=len(vals);wins=int((vals>0).sum())
            assert row[name]['trades']==n and row[name]['wins']==wins
            if n:assert near(row[name]['net_win_rate_pct'],100*wins/n) and near(row[name]['mean_net_pct_notional'],100*vals.mean())
        assert row['candidate_events']==row['known_no_order']+row['paired_unknown']+row['paired_verified']
    out={'all_checks_pass':True,'year':year,'audited_one_r_paths':checked,'matched_risk_archives':len(matched),'maximum_net_fraction_error':maxerr,
         'note':'Independent arithmetic on matched unit paths; no shared account or actual fills.'}
    (H/f'{year}一秒一倍账本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY1R58_LEDGER_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
