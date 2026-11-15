"""Independently reconcile all verified dynamic-path fees, funding and mark risks."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;M=60_000
def near(a,b):return abs(float(a)-float(b))<=1e-10*max(1.,abs(float(a)),abs(float(b)))
def main():
    arg=sys.argv[1] if len(sys.argv)>1 else '2024'
    assert arg in ('2024','2026')
    training=False;backup=False;follow=False
    outdir=HERE/('2024后续比较批次' if arg=='2024' else '2026后续比较批次')
    cache=ROOT/'work'/'point_in_time_universe33'/('risk_model_validation_'+arg)
    ledger=pd.read_parquet(outdir/'动态池单位收益与风险.parquet')
    manifest=json.loads((outdir/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    expected={(r['kind'],r['contract'],r['month']):r for r in manifest}
    marks={};funds={};matched=set()
    for path in cache.glob('*.json'):
        rec=json.loads(path.read_text(encoding='utf-8'));key=(rec['kind'],rec['contract'],rec['month'])
        if key not in expected or rec['sha256']!=expected[key].get('sha256'):continue
        matched.add(key)
        if rec['kind']=='markPriceKlines':
            for z in rec['rows']:marks[(rec['contract'],int(z['ts']))]=z
        else:funds[(rec['contract'],rec['month'])]=rec['rows']
    assert len(matched)==sum(r['status']=='verified' for r in manifest)
    checks=0;funding_count=0;max_error=0.;proxy=0
    for r in ledger.itertuples(index=False):
        if r.risk_status!='verified':continue
        side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005)
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill)
        assert r.entry_ts>=r.decision_ts+(15_000 if follow else 10_000) and r.exit_ts>=r.exit_signal_ts+5_000
        qty=1/entry;pay=0.;events=[];adverse=[]
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            mark=marks[(r.contract,ts)];adverse.append(float(mark['low'] if side==1 else mark['high']))
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            for f in funds.get((r.contract,month),[]):
                ft=int(f['ts'])
                if ft//M*M!=ts or not r.entry_ts<=ft<=r.exit_ts:continue
                amount=side*qty*float(mark['open'])*float(f['last_funding_rate'])
                amount=max(0.,amount) if ft in (r.entry_ts,r.exit_ts) else amount
                pay+=amount;events.append(ft);funding_count+=1
        assert near(pay,r.funding)
        recorded=json.loads(r.funding_events_json);assert sorted(events)==sorted(int(x['settlement_ts']) for x in recorded)
        exitfee=qty*exit*.0005;net=side*qty*(exit-entry)-.0005-exitfee-pay
        assert near(r.entry_fee,.0005) and near(r.exit_fee,exitfee)
        err=abs(net-float(r.net_per_unit_notional));max_error=max(max_error,err);assert near(net,r.net_per_unit_notional)
        lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
        hit=any(1/lev-.0005-max(pay,0.)+side*qty*(x-entry)<=qty*x*.01 for x in adverse)
        assert hit==bool(r.liq_proxy);proxy+=int(hit);checks+=1
    diagnostic=outdir/'不完整数据下单位机会诊断.json'
    if diagnostic.exists():
        x=json.loads(diagnostic.read_text(encoding='utf-8'))
        for row in x['rows']:
            n=row['verified_subset_events'];w=row['verified_subset_wins'];u=row['possible_unknown_events'];den=n+u
            if den:
                assert near(row['unit_win_rate_lower_pct'],100*w/den)
                assert near(row['unit_win_rate_upper_pct'],100*(w+u)/den)
    out={'validation_year':arg,'backup_variant':backup,'follow_variant':follow,'ledger_rows':len(ledger),'independently_checked_verified_paths':checks,
         'funding_events_checked':funding_count,'maximum_net_fraction_error':max_error,'liq_proxy_paths':proxy,
         'verified_archive_manifests_matched':len(matched),'unknown_win_count_bounds_rechecked':diagnostic.exists(),
         'note':'Only verified unit paths are reconciled. Unknown inputs and real account constraints remain separate.'}
    (outdir/'动态池净账本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_LEDGER_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
