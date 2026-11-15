import hashlib
import cadence_engine as e
from test_selection import synthetic

def main():
    z,f=synthetic()
    first=int(e.pd.Timestamp('2025-01-01 01:00',tz='UTC').timestamp())
    for ts,row in z['trace'].items():
        if ts>=first:row['daily_top2']=[]
    r=e.simulate('2025-01-01','2025-01-04','control_12h__fixed1',fixture=z,feature_fixture=f)
    assert r['trades'][0]['exit_ts']==first+11*3600
    assert len(r['selection_trace'])==8
    z,f=synthetic()
    r=e.simulate('2025-01-01','2025-01-04','control_12h__tiered',fixture=z,feature_fixture=f)
    assert r['core_trades']==1
    adds=[o for o in r['orders'] if o['reason']=='leverage_add']
    assert len(adds)==8 and all(o['ts']%86400==0 and o['stop_risk_pct']<=2 for o in adds)
    parent=e.base.read(e.previous.ROOT/'frozen.json')['files']
    for path,sha in parent.items():assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    frozen=dict(parent)
    for path in (e.ROOT/'protocol.json',e.ROOT/'cadence_engine.py',e.previous.ROOT/'official-protocol.json'):
        frozen[str(path.relative_to(e.ROOT.parent))]=hashlib.sha256(path.read_bytes()).hexdigest()
    checks=['合成数据验证：1点排名变化等到12点执行，不使用中间小时提前换币','每12小时重新评估不强迫交易，杠杆仍只在每日评估并受原2%风险约束','上一轮因子、数据、费用与风控代码哈希保持不变']
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    e.base.dump(e.ROOT/'frozen.json',dict(created_utc=e.pd.Timestamp.now(tz='UTC').isoformat(),files=frozen))
    print('12h preflight passed; rules frozen before outcomes',flush=True)

if __name__=='__main__':main()
