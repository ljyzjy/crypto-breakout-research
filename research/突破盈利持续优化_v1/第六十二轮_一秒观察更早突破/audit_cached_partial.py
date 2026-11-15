"""Arithmetic audit of the incomplete 2026 cache batch; not a tape audit."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60000
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    B=H/'2026一秒观察分批';local_path=H/'2026本地风险来源核验.json';local=json.loads(local_path.read_text(encoding='utf-8'))
    audit=json.loads((H/'2026本地风险独立核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass'] and audit['manifest_sha256']==sha(local_path)
    manifest=json.loads((B/'动态池风险档案核验清单.json').read_text(encoding='utf-8'));expected={(x['kind'],x['contract'],x['month']):x for x in manifest}
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46';files=list(cache.glob('*.json'))
    for a in local['archives']:assert sha(Path(a['cache_path']))==a['cache_sha256'];files.append(Path(a['cache_path']))
    marks={};funds={};matched=set()
    for file in files:
        z=json.loads(file.read_text(encoding='utf-8'));key=(z['kind'],z['contract'],z['month'])
        if key not in expected or expected[key].get('sha256')!=z.get('sha256'):continue
        matched.add(key)
        if z['kind']=='markPriceKlines':
            for x in z['rows']:marks[(z['contract'],int(x['ts']))]=x
        else:funds[(z['contract'],z['month'])]=z['rows']
    assert len(matched)==len(manifest);ledger=pd.read_parquet(B/'动态池单位收益与风险.parquet');checked=0;maxerr=0.
    for r in ledger.itertuples(index=False):
        assert r.risk_status=='verified';side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005);qty=1/entry
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill) and r.entry_ts>=r.entry_signal_reference_ts+1000 and r.exit_ts>=r.exit_signal_ts+5000
        funding=0.;events=[];extremes=[]
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            mark=marks[(r.contract,ts)];extremes.append(float(mark['low'] if side==1 else mark['high']))
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            for x in funds.get((r.contract,month),[]):
                ft=int(x['ts'])
                if ft//M*M!=ts or not r.entry_ts<=ft<=r.exit_ts:continue
                value=side*qty*float(mark['open'])*float(x['last_funding_rate'])
                funding+=max(0.,value) if ft in (r.entry_ts,r.exit_ts) else value;events.append(ft)
        assert near(funding,r.funding) and sorted(events)==sorted(int(x['settlement_ts']) for x in json.loads(r.funding_events_json))
        net=side*qty*(exit-entry)-.0005-qty*exit*.0005-funding;lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
        assert near(net,r.net_per_unit_notional) and near(r.entry_fee,.0005) and near(r.exit_fee,qty*exit*.0005)
        assert any(1/lev-.0005-max(funding,0.)+side*qty*(v-entry)<=qty*v*.01 for v in extremes)==bool(r.liq_proxy)
        maxerr=max(maxerr,abs(net-r.net_per_unit_notional));checked+=1
    assert checked==8
    out={'arithmetic_checks_pass':True,'audited_risk_paths':checked,'matched_risk_archives':len(matched),'maximum_net_fraction_error':maxerr,
         'source_paths_sha256':sha(B/'动态池延迟市价路径.parquet'),'ledger_sha256':sha(B/'动态池单位收益与风险.parquet'),
         'local_audit_sha256':sha(H/'2026本地风险独立核验.json'),'public_tape_sample_audit_complete':False,
         'note':'Partial cost and risk arithmetic only; 22 groups pending and source-tape audit not yet done.'}
    (H/'2026中间批次风险算术核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_PARTIAL_RISK_ARITHMETIC_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
