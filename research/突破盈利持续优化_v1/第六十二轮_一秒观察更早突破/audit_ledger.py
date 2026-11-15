"""Independently check cost, risk and complete-candidate accounting."""
import hashlib,json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60000
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main(year):
    I=H/f'{year}冻结输入';B=H/f'{year}一秒观察分批';samples=json.loads((H/f'{year}一秒观察逐笔独立核验.json').read_text(encoding='utf-8'))
    assert samples['all_checks_pass']
    manifest=json.loads((B/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    expected={(x['kind'],x['contract'],x['month']):x for x in manifest};matched=set();marks={};funds={}
    folder='risk_old11_2023_serialv1' if year=='2023' else 'risk_fixed11_cross46';cache=ROOT/'work'/'point_in_time_universe33'/folder
    files=list(cache.glob('*.json'));local_path=H/'2026本地风险来源核验.json'
    if year=='2026' and local_path.exists():
        local=json.loads(local_path.read_text(encoding='utf-8'));check=json.loads((H/'2026本地风险独立核验.json').read_text(encoding='utf-8'))
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        assert local['all_checks_pass'] and check['all_checks_pass'] and check['manifest_sha256']==digest(local_path)
        assert check['audit_sha256']==digest(H/'audit_local_risk.py')
        for x in local['archives']:
            assert digest(Path(x['cache_path']))==x['cache_sha256'];files.append(Path(x['cache_path']))
    for file in files:
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
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill) and r.entry_ts>=r.entry_signal_reference_ts+1000
        assert r.entry_signal_reference_ts>=r.decision_ts+1000 and r.exit_ts>=r.exit_signal_ts+5000
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
    signal=pd.read_parquet(B/'动态池逐笔信号筛查.parquet');detail=pd.read_parquet(H/f'{year}一秒观察已核验机会.parquet')
    results=json.loads((H/f'{year}一秒观察对照.json').read_text(encoding='utf-8'))['rows']
    baseline=json.loads((I/'baseline_summary.json').read_text(encoding='utf-8'))['rows']
    for row in results:
        lev=row['leverage'];d=detail[detail.leverage.eq(lev)].set_index('observation_id')
        index=ledger[ledger.variant.eq(f'one_observation_2r_{lev}x')].set_index('observation_id');known=[];unknown=0;noorder=0
        for r in signal.itertuples(index=False):
            if r.status not in BENIGN:unknown+=1;continue
            if r.status!='qualified':noorder+=1;continue
            pre=getattr(r,f'precheck_{lev}x')
            if pd.isna(pre):unknown+=1;continue
            if pre!='passed':noorder+=1;continue
            if r.observation_id not in index.index:unknown+=1;continue
            z=index.loc[r.observation_id]
            if z.risk_status!='verified' or bool(z.liq_proxy):unknown+=1;continue
            known.append(r.observation_id)
        assert set(known)==set(d.index) and unknown==row['one_second_observation']['unknown'] and noorder==row['known_no_order']
        for obs in known:assert near(d.loc[obs,'net_per_unit_notional'],index.loc[obs,'net_per_unit_notional'])
        vals=d.net_per_unit_notional.astype(float);n=len(vals);wins=int((vals>0).sum());item=row['one_second_observation']
        assert item['trades']==n and item['wins']==wins and n+unknown+noorder==len(signal)
        if n:assert near(item['net_win_rate_pct'],100*wins/n) and near(item['mean_net_pct_notional'],100*vals.mean())
        old=next(x for x in baseline if x['year']==year and x['strategy']=='baseline' and x['leverage']==lev)
        assert row['five_second_observation_baseline']['trades']==old['verified_events'] and row['five_second_observation_baseline']['wins']==old['verified_wins']
    out={'all_checks_pass':True,'year':year,'audited_one_second_observation_paths':checked,'matched_risk_archives':len(matched),
         'maximum_net_fraction_error':maxerr,'note':'Known unit paths and all candidate statuses, not shared account or actual fills.'}
    (H/f'{year}一秒观察账本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_LEDGER_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
