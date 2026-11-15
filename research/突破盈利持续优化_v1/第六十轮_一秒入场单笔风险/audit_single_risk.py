"""Independently verify all descriptive unit and margin calculations."""
import csv,hashlib,json,math
from collections import defaultdict
from decimal import Decimal,getcontext
from pathlib import Path
import pandas as pd
getcontext().prec=32
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
def main():
    output=H/'一秒已知机会单笔风险.json';detail=H/'一秒已知机会单笔风险.csv';z=json.loads(output.read_text(encoding='utf-8'))
    for path,digest in z['source_sha256'].items():assert sha(Path(path))==digest
    originals={}
    for year in ('2024','2026'):
        d=pd.read_parquet(R58/f'{year}冻结输入'/'pair_details.parquet')
        for r in d.itertuples(index=False):originals[(year,int(r.leverage),r.observation_id)]=Decimal(str(r.one_second_net))*100
    with detail.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    groups=defaultdict(list);seen=set()
    for r in rows:
        year=r['year'];lev=int(r['leverage']);key=(year,lev,r['observation_id']);assert key not in seen;seen.add(key)
        assert near(r['net_pct_notional'],originals[key]) and near(r['net_pct_assumed_margin'],originals[key]*lev)
        groups[(year,lev)].append(originals[key])
    assert len(rows)==len(originals)
    for row in z['rows']:
        vals=groups[(row['year'],row['leverage'])];win=[x for x in vals if x>0];loss=[x for x in vals if x<0]
        assert len(vals)==row['verified_trades'] and len(win)==row['wins'] and len(loss)==row['losses']
        assert near(sum(win,Decimal(0))/len(win),row['mean_win_pct_notional'])
        assert near(sum(loss,Decimal(0))/len(loss),row['mean_loss_pct_notional'])
        assert near(min(vals),row['worst_pct_notional']) and near(max(vals),row['best_pct_notional'])
        assert near(min(vals)*row['leverage'],row['worst_pct_assumed_isolated_margin'])
    audit={'all_checks_pass':True,'paths_checked':len(rows),'groups_checked':len(groups),
           'output_sha256':sha(output),'detail_sha256':sha(detail),'audit_sha256':sha(Path(__file__)),
           'note':'Decimal arithmetic; conditional margin assumption, not shared-account drawdown.'}
    (H/'一秒已知机会单笔风险独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SINGLE_RISK60_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
