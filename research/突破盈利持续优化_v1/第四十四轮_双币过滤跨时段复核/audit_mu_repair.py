"""Independently reconcile daily-mark repair, risk proxy, costs and aggregates."""
import hashlib,json,math
from pathlib import Path
import pandas as pd,requests
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;B=H/'2026_修复前冻结';M=60_000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    probe=json.loads((H/'MU标记价日档来源核验.json').read_text(encoding='utf-8'))
    result=json.loads((H/'MU标记价修复后诊断.json').read_text(encoding='utf-8'))
    file=Path(probe['daily_local_path']);assert hashlib.sha256(file.read_bytes()).hexdigest()==probe['daily_sha256']
    url='https://data.binance.vision/data/futures/um/daily/markPriceKlines/MUUSDT/1m/MUUSDT-1m-2026-06-29.zip.CHECKSUM'
    response=requests.get(url,timeout=(15,50));response.raise_for_status();assert response.text.strip().split()[0].lower()==probe['daily_sha256']
    daily=pd.read_csv(file,compression='zip').set_index('open_time');ledger=pd.read_parquet(B/'动态池单位收益与风险.parquet')
    before=json.loads((B/'跨时段双币过滤诊断.json').read_text(encoding='utf-8'))
    fund=[];cache=ROOT/'work'/'point_in_time_universe33'/'risk_cross44'
    expected=json.loads((B/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    fr=next(x for x in expected if x['contract']=='MUUSDT' and x['month']=='2026-06' and x['kind']=='fundingRate')
    for p in cache.glob('*.json'):
        rec=json.loads(p.read_text(encoding='utf-8'))
        if rec['contract']=='MUUSDT' and rec['month']=='2026-06' and rec['kind']=='fundingRate' and rec['sha256']==fr['sha256']:fund=rec['rows']
    assert fund and probe['overlap_rows']==0 and probe['needed_minutes']==probe['missing_available_in_day']==9
    checked=[]
    for fix in result['repaired_paths']:
        r=ledger[(ledger.observation_id.eq(fix['observation_id']))&(ledger.variant.eq(fix['variant']))].iloc[0]
        assert r.risk_status=='missing_mark_minute'
        side=int(r.side);entry=float(r.entry_raw)*(1+side*.0005);exit=float(r.exit_raw)*(1-side*.0005);qty=1/entry
        assert near(entry,r.entry_fill) and near(exit,r.exit_fill)
        pay=0.;adverse=[];events=[]
        for t in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            bar=daily.loc[t];adverse.append(float(bar['low'] if side==1 else bar['high']))
            for item in fund:
                ft=int(item['ts'])
                if ft//M*M!=t or not r.entry_ts<=ft<=r.exit_ts:continue
                amount=side*qty*float(bar['open'])*float(item['last_funding_rate'])
                pay+=max(0.,amount) if ft in (r.entry_ts,r.exit_ts) else amount;events.append(ft)
        net=side*qty*(exit-entry)-.0005-qty*exit*.0005-pay;lev=int(r.variant.rsplit('_',1)[1].rstrip('x'))
        hit=any(1/lev-.0005-max(pay,0.)+side*qty*(v-entry)<=qty*v*.01 for v in adverse)
        assert near(net,fix['net_per_unit_notional']) and near(pay,fix['funding']) and hit==fix['liq_proxy']
        assert sorted(events)==sorted(int(x['settlement_ts']) for x in json.loads(fix['funding_events_json']))
        checked.append({'variant':r.variant,'net_pct_notional':100*net,'proxy_hit':hit})
    for row in result['rows']:
        lev=row['leverage'];prior=next(x for x in before['rows'] if x['period']=='2026_may_jul' and x['leverage']==lev)
        fix=next(x for x in result['repaired_paths'] if x['variant']==f'normal_2r_{lev}x')
        ids=set(prior['verified_observation_ids']);unknown=set(prior['unknown_observation_ids']);obs=fix['observation_id']
        base=ledger[ledger.observation_id.isin(ids)&ledger.variant.eq(f'normal_2r_{lev}x')]
        vals=[float(x) for x in base.net_per_unit_notional]
        if not fix['liq_proxy']:vals.append(float(fix['net_per_unit_notional']));ids.add(obs);unknown.remove(obs)
        n=len(vals);w=sum(x>0 for x in vals);u=len(unknown);pos=sum(x for x in vals if x>0);neg=-sum(x for x in vals if x<0)
        assert set(row['verified_observation_ids'])==ids and set(row['unknown_observation_ids'])==unknown
        assert row['verified_events']==n and row['verified_wins']==w and row['possible_unknown_events']==u
        assert near(row['verified_win_rate_pct'],100*w/n) and near(row['mean_net_pct_notional'],100*sum(vals)/n)
        assert near(row['profit_factor'],pos/neg) and near(row['unit_win_rate_upper_pct'],100*(w+u)/(n+u))
    out={'independently_checked_paths':len(checked),'checked':checked,'official_daily_checksum_rechecked':True,
         'monthly_daily_overlap_minutes':0,'all_checks_pass':True,
         'note':'No monthly/day overlap on this date; daily source is checksum-verified but not cross-checked against overlapping monthly minutes.'}
    (H/'MU标记价修复独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_MU_REPAIR_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
