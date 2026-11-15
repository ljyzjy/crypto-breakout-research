"""Independently recompute exit-only slippage costs and groups using Decimal."""
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
    outpath=H/'退出滑点压力对照.json';detail=H/'退出滑点压力逐笔.csv';z=json.loads(outpath.read_text(encoding='utf-8'))
    for path,digest in z['source_sha256'].items():assert sha(Path(path))==digest
    origin={}
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';ledger=pd.read_parquet(I/'ledger_2r.parquet')
        for r in ledger.itertuples(index=False):origin[(year,int(r.variant.rsplit('_',1)[1].rstrip('x')),r.observation_id)]=r
    with detail.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    groups=defaultdict(list);seen=set()
    for row in rows:
        key=(row['year'],int(row['leverage']),row['observation_id']);r=origin[key]
        tag=(*key,row['exit_slip']);assert tag not in seen;seen.add(tag)
        slip=dec(row['exit_slip']);assert slip in (Decimal('0.0005'),Decimal('0.00075'),Decimal('0.001'))
        assert r.risk_status=='verified' and not r.liq_proxy
        entry=dec(r.entry_fill);exit=dec(r.exit_raw)*(Decimal(1)-dec(r.side)*slip);fee=exit/entry*Decimal('0.0005')
        net=dec(r.side)*(exit-entry)/entry-Decimal('0.0005')-fee-dec(r.funding)
        assert near(row['exit_fill'],exit) and near(row['exit_fee'],fee) and near(row['funding'],r.funding) and near(row['net'],net)
        groups[(row['year'],int(row['leverage']),slip)].append((net,int(r.entry_ts)))
    for group in z['rows']:
        for s in group['scenarios']:
            slip=dec(s['exit_slippage_pct'])/100;items=groups[(group['year'],group['leverage'],slip)]
            vals=[v for v,_ in items];n=len(vals);wins=sum(v>0 for v in vals);plus=sum((v for v in vals if v>0),Decimal(0));loss=-sum((v for v in vals if v<0),Decimal(0))
            days={pd.Timestamp(t,unit='ms',tz='UTC').date() for _,t in items}
            assert n==s['trades'] and wins==s['wins'] and len(days)==s['active_utc_days']
            assert near(s['win_rate_pct'],100*wins/n) and near(s['mean_net_pct_notional'],100*sum(vals,Decimal(0))/n) and near(s['profit_factor'],plus/loss)
    audit={'all_checks_pass':True,'scenario_paths_checked':len(rows),'aggregate_groups_checked':len(groups),
           'result_sha256':sha(outpath),'detail_sha256':sha(detail),'audit_code_sha256':sha(Path(__file__)),
           'note':'Independent Decimal exit cost and aggregation; source ledgers remain frozen.'}
    (H/'退出滑点压力独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT_SLIP59_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
