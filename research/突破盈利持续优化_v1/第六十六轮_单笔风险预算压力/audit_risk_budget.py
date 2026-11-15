"""Independently recompute reference-time sizing and realized per-trade loss."""
import csv,hashlib,json,math
from collections import defaultdict
from decimal import Decimal,getcontext
from pathlib import Path
import pandas as pd
getcontext().prec=32
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dec(x):return Decimal(str(x))
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
def main():
    out=H/'单笔风险预算情景.json';detail=H/'单笔风险预算逐笔.csv';z=json.loads(out.read_text(encoding='utf-8'))
    for path,digest in z['source_sha256'].items():assert sha(Path(path))==digest
    events={};ledger={}
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';e=pd.read_parquet(I/'events.parquet');l=pd.read_parquet(I/'ledger_2r.parquet')
        for x in e.itertuples(index=False):events[(year,x.observation_id)]=x
        for x in l.itertuples(index=False):ledger[(year,int(x.variant.rsplit('_',1)[1].rstrip('x')),x.observation_id)]=x
    with detail.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    groups=defaultdict(list);seen=set()
    for r in rows:
        key=(r['year'],int(r['leverage']),r['observation_id']);assert key not in seen;seen.add(key)
        e=events[(key[0],key[2])];x=ledger[key];side=dec(e.side);lev=Decimal(key[1]);reference=dec(e.raw_entry_5s);stop=dec(e.stop_price)
        assert int(e.entry_exec_ts)<=int(x.entry_ts) and int(side)==int(x.side)
        est=reference*(1+side*Decimal('.0005'));exit_est=stop*(1-side*Decimal('.0005'))
        cash_loss=-(side*(exit_est-est)-Decimal('.0005')*est-Decimal('.0005')*exit_est)
        qty=min(Decimal('.005')/cash_loss,1/(est*(1/lev+Decimal('.0005'))))
        planned=qty*cash_loss;cost_est=qty*est*(1/lev+Decimal('.0005'))
        cost_actual=qty*dec(x.entry_fill)*(1/lev+Decimal('.0005'))
        actual=qty*dec(x.entry_fill)*dec(x.net_per_unit_notional)
        for name,val in [('estimated_entry',est),('estimated_stop_fill',exit_est),('quantity_per_initial_equity',qty),
                         ('planned_loss_fraction_equity',planned),('estimated_initial_cost_fraction',cost_est),
                         ('actual_initial_cost_fraction',cost_actual),('realized_fraction_equity',actual)]:assert near(r[name],val)
        groups[(key[0],key[1])].append((planned,actual,cost_est,cost_actual,x.reason))
    for r in z['rows']:
        g=groups[(r['year'],r['leverage'])];n=len(g);assert n==r['verified_trades']
        assert sum(x[1]<Decimal('-.005000000001') for x in g)==r['loss_over_budget_count']
        assert sum(x[2]>=Decimal('.999999999999') for x in g)==r['cash_cap_binding_count']
        assert sum(x[3]>Decimal('1.000000000001') for x in g)==r['realized_initial_cost_over_equity_count']
        assert sum(x[4]=='filled_beyond_risk_budget' for x in g)==r['risk_budget_breach_fill_count']
        assert near(100*sum((x[0] for x in g),Decimal(0))/n,r['mean_planned_loss_pct_equity'])
        assert near(100*min(x[1] for x in g),r['worst_actual_result_pct_equity'])
        assert near(100*sum((x[1] for x in g),Decimal(0))/n,r['mean_actual_result_pct_equity'])
    audit={'all_checks_pass':True,'paths_checked':len(rows),'groups_checked':len(groups),
           'output_sha256':sha(out),'detail_sha256':sha(detail),'audit_sha256':sha(Path(__file__)),
           'note':'Independent Decimal reference-time sizing; hypothetical isolated trade, no account replay.'}
    (H/'单笔风险预算独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RISK_BUDGET66_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
