"""Independently check stop price counterfactual and aggregate arithmetic."""
import csv,hashlib,json,math
from collections import defaultdict
from decimal import Decimal,getcontext
from pathlib import Path
import pandas as pd
getcontext().prec=32
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
def dec(x):return Decimal(str(x))
def main():
    out=H/'止损退出价格差距.json';detail=H/'止损退出价格差距逐笔.csv';z=json.loads(out.read_text(encoding='utf-8'))
    for p,d in z['source_sha256'].items():assert sha(Path(p))==d
    source={}
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';pairs=pd.read_parquet(I/'pair_details.parquet');ledger=pd.read_parquet(I/'ledger_2r.parquet')
        for lev in (10,20):
            ids=set(pairs.loc[pairs.leverage.eq(lev),'observation_id']);d=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')&ledger.observation_id.isin(ids)&ledger.reason.eq('stop')]
            for r in d.itertuples(index=False):source[(year,lev,r.observation_id)]=r
    with detail.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    grouped=defaultdict(list);seen=set()
    for r in rows:
        key=(r['year'],int(r['leverage']),r['observation_id']);assert key not in seen;seen.add(key);x=source[key]
        entry=dec(x.entry_fill);side=dec(x.side);ideal_fill=dec(x.initial_stop)*(Decimal(1)-side*Decimal('.0005'))
        ideal=side*(ideal_fill-entry)/entry-Decimal('.0005')-ideal_fill/entry*Decimal('.0005')-dec(x.funding)
        actual=dec(x.net_per_unit_notional);gap=ideal-actual
        assert near(r['ideal_stop_fill'],ideal_fill) and near(r['ideal_stop_net'],ideal) and near(r['actual_net'],actual) and near(r['extra_loss'],gap)
        grouped[(key[0],key[1])].append((actual,ideal,gap))
    assert seen==set(source)
    for r in z['rows']:
        g=grouped[(r['year'],r['leverage'])];n=len(g);a=[x[0] for x in g];i=[x[1] for x in g];d=[x[2] for x in g]
        assert n==r['known_stop_trades'] and sum(x>Decimal('0.000000000001') for x in d)==r['worse_than_ideal_count']
        assert near(100*sum(a,Decimal(0))/n,r['avg_actual_pct_notional']) and near(100*sum(i,Decimal(0))/n,r['avg_ideal_pct_notional'])
        assert near(100*sum(d,Decimal(0))/n,r['avg_extra_loss_pct_notional']) and near(100*min(a),r['worst_actual_pct_notional'])
        assert near(100*max(d),r['largest_extra_loss_pct_notional']) and near(100*r['leverage']*max(d),r['largest_extra_loss_pct_assumed_margin'])
    audit={'all_checks_pass':True,'stop_paths_checked':len(rows),'groups_checked':len(grouped),
        'result_sha256':sha(out),'detail_sha256':sha(detail),'audit_sha256':sha(Path(__file__)),
        'note':'Decimal calculation versus idealized stop fill, not actual executions.'}
    (H/'止损退出价格差距独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('STOP_GAP64_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
