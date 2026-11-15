"""Independently recompute the funded-gate 2024 unit aggregates."""
import csv, hashlib, json, math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pandas as pd

H=Path(__file__).resolve().parent; P=H.parent
FAST=P/'第五十一轮_缩短市价入场延迟'; FUND=P/'第五十五轮_WorkBuddy资金费假说'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b): return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-10)
def main():
    output=H/'2024资金费门完整逐笔配对.json'; detail=H/'2024资金费门完整逐笔.csv'
    z=json.loads(output.read_text(encoding='utf-8'))
    for path,digest in z['source_sha256'].items(): assert sha(Path(path))==digest
    gate_file=FUND/'已核验机会及资金费门.csv'; audited=json.loads((FUND/'资金费门独立核验.json').read_text(encoding='utf-8'))
    assert audited['all_checks_pass'] and audited['detail_sha256']==sha(gate_file)
    with gate_file.open(encoding='utf-8-sig',newline='') as f:
        gate={(r['observation_id'],int(r['leverage'])):r for r in csv.DictReader(f) if r['year']=='2024'}
    raw=pd.read_parquet(FAST/'2024一秒五秒逐笔配对结果.parquet')
    original={(r.observation_id,int(r.leverage)):r for r in raw.itertuples(index=False)}
    assert len(original)==len(raw)
    with detail.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    assert len(rows)==len(original) and len({(r['observation_id'],int(r['leverage'])) for r in rows})==len(rows)
    for r in rows:
        key=(r['observation_id'],int(r['leverage'])); a=original[key]; g=gate[key]
        assert r['allowed'] in ('True','False') and r['allowed']==g['allowed']
        assert int(r['decision_ts'])==int(g['decision_ts']) and int(r['side'])==int(g['side'])
        assert int(r['one_second_entry_ts'])==int(a.one_second_entry_ts)
        assert near(r['one_second_net'],a.one_second_net) and near(r['five_second_net'],a.five_second_net)
        assert near(r['five_second_net'],g['net_per_unit_notional'])
    checks=0
    for result in z['rows']:
        lev=result['leverage']; members=[r for r in rows if int(r['leverage'])==lev]
        assert len(members)==result['baseline_one_second']['trades']
        filtered=[r for r in members if r['allowed']=='True']
        assert len(members)-len(filtered)==result['known_filtered']
        for name, subset, col in [('baseline_one_second',members,'one_second_net'),('gate_one_second',filtered,'one_second_net'),
                                  ('baseline_five_second',members,'five_second_net'),('gate_five_second',filtered,'five_second_net')]:
            target=result[name]; values=[Decimal(x[col]) for x in subset]; n=len(values); wins=sum(x>0 for x in values)
            positive=sum((x for x in values if x>0),Decimal(0)); negative=-sum((x for x in values if x<0),Decimal(0))
            active={datetime.fromtimestamp(int(x['one_second_entry_ts'])/1000,tz=timezone.utc).date() for x in subset}
            assert n==target['trades'] and wins==target['wins'] and len(active)==target['active_utc_days']
            assert target['unknown']==16 and near(target['win_rate_pct'],100*wins/n)
            assert near(target['mean_net_pct_notional'],100*sum(values,Decimal(0))/n)
            assert near(target['profit_factor'],positive/negative)
            assert near(target['optimistic_upper_pct'],100*(wins+16)/(n+16)); checks+=1
    record={'all_checks_pass':True,'paired_paths_checked':len(rows),'aggregate_groups_checked':checks,
            'result_sha256':sha(output),'detail_sha256':sha(detail),'audit_code_sha256':sha(Path(__file__)),
            'note':'Independent Decimal aggregation of all paired rows; funding gate itself audited in round 55.'}
    (H/'2024资金费门完整逐笔独立核验.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FUNDING56_INDEPENDENT_PASS',json.dumps(record,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
