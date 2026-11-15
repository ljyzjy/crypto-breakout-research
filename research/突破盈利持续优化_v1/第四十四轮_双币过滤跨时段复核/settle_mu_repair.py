"""Apply one validated daily mark repair without changing the frozen prior result."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
import settle_cross_engine as engine
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;BEFORE=H/'2026_修复前冻结'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    source=json.loads((H/'MU标记价日档来源核验.json').read_text(encoding='utf-8'));assert source['repair_safe']
    file=Path(source['daily_local_path']);assert sha(file)==source['daily_sha256']
    checks=json.loads((BEFORE/'冻结哈希.json').read_text(encoding='utf-8'))
    for n,v in checks.items():assert sha(BEFORE/n)==v
    ledger=pd.read_parquet(BEFORE/'动态池单位收益与风险.parquet');report=json.loads((BEFORE/'跨时段双币过滤诊断.json').read_text(encoding='utf-8'))
    manifest=json.loads((BEFORE/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    status={(x['kind'],x['contract'],x['month']):x['status'] for x in manifest}
    cache=ROOT/'work'/'point_in_time_universe33'/'risk_cross44';marks={};funds={}
    for p in cache.glob('*.json'):
        z=json.loads(p.read_text(encoding='utf-8'))
        if z['contract']!='MUUSDT' or z['month']!='2026-06':continue
        expected=next((m for m in manifest if m['contract']==z['contract'] and m['kind']==z['kind'] and m['month']==z['month']),None)
        if not expected or expected.get('sha256')!=z['sha256']:continue
        if z['kind']=='markPriceKlines':
            for r in z['rows']:marks[(z['contract'],int(r['ts']))]=r
        elif z['kind']=='fundingRate':funds[(z['contract'],z['month'])]=z['rows']
    daily=pd.read_csv(file,compression='zip')[['open_time','open','high','low','close']].apply(pd.to_numeric,errors='raise')
    daily=daily[daily.open_time.isin(source['needed_timestamps'])]
    assert len(daily)==9 and not daily.open_time.duplicated().any()
    for r in daily.to_dict('records'):
        key=('MUUSDT',int(r['open_time']));assert key not in marks
        marks[key]={'ts':int(r.pop('open_time')),**r}
    target=ledger[ledger.risk_status.eq('missing_mark_minute')]
    assert len(target)==2 and target.observation_id.nunique()==1 and set(target.variant)=={'normal_2r_10x','normal_2r_20x'}
    repaired=[]
    for r in target.itertuples(index=False):
        z=engine.settle(r,marks,funds,status);assert z['risk_status']=='verified'
        repaired.append({'observation_id':r.observation_id,'variant':r.variant,**z})
    result=[]
    for lev in (10,20):
        old=next(x for x in report['rows'] if x['period']=='2026_may_jul' and x['leverage']==lev)
        fix=next(x for x in repaired if x['variant']==f'normal_2r_{lev}x')
        ids=set(old['verified_observation_ids']);unknown=set(old['unknown_observation_ids']);obs=fix['observation_id']
        assert obs in unknown and obs not in ids
        baseline=ledger[ledger.observation_id.isin(ids)&ledger.variant.eq(f'normal_2r_{lev}x')]
        assert len(baseline)==len(ids)
        vals=list(map(float,baseline.net_per_unit_notional))
        if not fix['liq_proxy']:
            vals.append(float(fix['net_per_unit_notional']));ids.add(obs);unknown.remove(obs)
        n=len(vals);u=len(unknown);w=sum(x>0 for x in vals);pos=sum(x for x in vals if x>0);neg=-sum(x for x in vals if x<0)
        result.append({'period':'2026_may_jul','leverage':lev,'verified_events':n,'verified_wins':w,
             'verified_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(np.mean(vals)) if n else None,
             'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
             'unit_win_rate_upper_pct':100*(w+u)/(n+u) if n+u else None,
             'known_no_order':old['known_no_order'],'verified_observation_ids':sorted(ids),'unknown_observation_ids':sorted(unknown)})
    out={'repair_plan_sha256':sha(H/'MU标记价日档修复规则.md'),'source_audit_sha256':sha(H/'MU标记价日档来源核验.json'),
         'repaired_paths':repaired,'rows':result,'note':'Mixed asset universe; independent unit paths, no account result.'}
    (H/'MU标记价修复后诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_MU_REPAIR_DIAGNOSIS',json.dumps({**out,'rows':[{k:v for k,v in r.items() if not k.endswith('_ids')} for r in result]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
