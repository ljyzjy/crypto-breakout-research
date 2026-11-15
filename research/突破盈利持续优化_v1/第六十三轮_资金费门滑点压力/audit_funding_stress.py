"""Independently check gate membership and scenario aggregates."""
import csv,hashlib,json,math
from collections import defaultdict
from decimal import Decimal,getcontext
from pathlib import Path
getcontext().prec=32
H=Path(__file__).resolve().parent;P=H.parent;R55=P/'第五十五轮_WorkBuddy资金费假说';R59=P/'第五十九轮_退出滑点压力'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
def main():
    output=H/'资金费门退出滑点压力.json';detail=H/'资金费门退出滑点逐笔.csv';z=json.loads(output.read_text(encoding='utf-8'))
    for path,digest in z['source_sha256'].items():assert sha(Path(path))==digest
    with (R55/'已核验机会及资金费门.csv').open(encoding='utf-8-sig',newline='') as f:
        gate={(r['year'],int(r['leverage']),r['observation_id']):r['allowed'] for r in csv.DictReader(f)}
    with (R59/'退出滑点压力逐笔.csv').open(encoding='utf-8-sig',newline='') as f:
        expected={(r['year'],int(r['leverage']),r['observation_id'],Decimal(r['exit_slip'])):Decimal(r['net']) for r in csv.DictReader(f) if gate[(r['year'],int(r['leverage']),r['observation_id'])]=='True'}
    with detail.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    groups=defaultdict(list);seen=set()
    for r in rows:
        key=(r['year'],int(r['leverage']),r['observation_id'],Decimal(r['exit_slip']))
        assert key not in seen and gate[key[:3]]=='True' and r['allowed']=='True' and near(r['net'],expected[key]);seen.add(key)
        groups[(key[0],key[1],key[3])].append(expected[key])
    assert seen==set(expected)
    for group in z['rows']:
        for result in group['scenarios']:
            key=(group['year'],group['leverage'],Decimal(str(result['exit_slippage_pct']))/100);v=groups[key]
            n=len(v);wins=sum(x>0 for x in v);positive=sum((x for x in v if x>0),Decimal(0));loss=-sum((x for x in v if x<0),Decimal(0))
            assert n==result['trades'] and wins==result['wins'] and result['unknown']==(16 if group['year']=='2024' else 4)
            assert near(result['net_win_rate_pct'],100*wins/n) and near(result['mean_net_pct_notional'],100*sum(v,Decimal(0))/n) and near(result['profit_factor'],positive/loss)
    audit={'all_checks_pass':True,'scenario_paths_checked':len(rows),'aggregate_groups_checked':len(groups),
           'output_sha256':sha(output),'detail_sha256':sha(detail),'audit_sha256':sha(Path(__file__)),
           'note':'Independent gate join and Decimal aggregation; prior exit costs independently checked in round 59.'}
    (H/'资金费门退出滑点独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FUNDING63_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
