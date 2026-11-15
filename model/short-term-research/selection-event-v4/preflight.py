import hashlib,gc,sys
from types import FunctionType
import event_engine as e
from test_dynamic import fixture

def synthetic():
    z,f=fixture();z['symbols']=('BTCUSDT','ETHUSDT','LTCUSDT')
    for field in ('px','mk','rates','ok','avail','mom','budgets'):
        z[field]['LTCUSDT']=z[field]['BTCUSDT'].copy()
    z['budgets']['ETHUSDT'][:]=50
    f['LTCUSDT']=f['BTCUSDT'].copy()
    z['trace']={}
    for t in e.pd.date_range('2025-01-01','2025-01-04 23:00',freq='h',tz='UTC'):
        z['trace'][int(t.timestamp())]=dict(date=t.isoformat(),ranked=[{'symbol':s} for s in ('ETHUSDT','BTCUSDT','LTCUSDT')],daily_top2=['ETHUSDT','BTCUSDT'])
    z=e.cadence.clock12(z,0)
    return z,f

def main():
    checks=[]
    z,f=synthetic();t0=int(z['index'][0].timestamp())
    for ts,row in z['trace'].items():
        if ts>t0:row['ranked']=[{'symbol':s} for s in ('LTCUSDT','ETHUSDT','BTCUSDT')]
    r=e.simulate('2025-01-01','2025-01-04','combined_event__fixed1',fixture=z,feature_fixture=f)
    opens=[o for o in r['orders'] if o['action']=='open']
    assert [o['symbol'] for o in opens]==['ETHUSDT','BTCUSDT']
    assert all(t['reason']=='window_end' for t in r['trades'])
    checks.append('排名改变或到12小时不强制卖出；初始两仓严格按排名而非币名排序')
    z,f=synthetic();at=e.pd.Timestamp('2025-01-01 13:00',tz='UTC');i=z['index'].get_loc(at)
    z['px']['BTCUSDT'][i,2]=94.;z['mk']['BTCUSDT'][i,2]=94.
    for ts,row in z['trace'].items():
        row['ranked']=[{'symbol':s} for s in ('BTCUSDT','ETHUSDT','LTCUSDT')]
    r=e.simulate('2025-01-01','2025-01-04','combined_event__fixed1',fixture=z,feature_fixture=f)
    replacement=[o for o in r['orders'] if o['action']=='open' and o['symbol']=='LTCUSDT']
    assert replacement[0]['ts']==int(at.timestamp())+300
    assert sum(t['symbol']=='ETHUSDT' and t['layer']=='core' for t in r['trades'])==1
    checks.append('卖出一仓后下根5分钟才补位；跳过已持仓和止损冷却币，选择最高合格名次，另一仓持续持有')
    z,f=synthetic();cut=e.pd.Timestamp('2025-01-01 12:00',tz='UTC')
    z['mom']['BTCUSDT'][z['index']>=cut]=0
    r=e.simulate('2025-01-01','2025-01-04','combined_event__fixed1',fixture=z,feature_fixture=f)
    exits=[o for o in r['orders'] if o['reason']=='timing_exit']
    assert exits[0]['ts']==int(cut.timestamp())
    assert next(o for o in r['orders'] if o['action']=='open' and o['symbol']=='LTCUSDT')['ts']==int(cut.timestamp())+300
    checks.append('方向退出仍在UTC00/12点；退出当根开盘不同时补位')
    print('\n'.join(checks),flush=True)
    if '--synthetic-only' in sys.argv:return
    # Newly acquired unused assets must not change the already-run controls.
    for selector in ('control','combined'):
        z=FunctionType(e.parent.prepare.__wrapped__.__code__,e.scope(),argdefs=e.parent.prepare.__wrapped__.__defaults__)(
            '2025-01-01','2026-04-26',selector+'_hourly',0)
        z=e.cadence.clock12(z,0)
        for variant in ('fixed1','tiered'):
            actual=e.parent.simulate('2025-01-01','2026-04-26',selector+'_hourly__'+variant,.0005,0,z,e.features())
            expected=e.cadence.cached_run('2025-01-01','2026-04-26',selector+'_12h__'+variant)
            for k in ('valid_for_comparison','return_pct','max_drawdown','fees','slippage_cost','funding_cost'):
                assert actual[k]==expected[k],(selector,variant,k,actual[k],expected[k])
        del z,actual,expected;e.load_frame.cache_clear();gc.collect()
    checks.append('扩展执行数据后，原动量与四因子12小时对照的1×/动态5×经济结果完全复现')
    frozen=e.base.read(e.cadence.ROOT/'frozen.json')['files']
    for path,sha in frozen.items():assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    for path in [e.ROOT/name for name in ('event_engine.py','event_execution.py','event_prepare.py','protocol.json','data-manifest.json','quarantine.json')]+list((e.ROOT/'signals').glob('*.json.gz')):
        frozen[str(path.relative_to(e.ROOT.parent))]=hashlib.sha256(path.read_bytes()).hexdigest()
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    e.base.dump(e.ROOT/'frozen.json',dict(created_utc=e.pd.Timestamp.now(tz='UTC').isoformat(),files=frozen))
    print('Event rules/data frozen before candidate outcomes',flush=True)

if __name__=='__main__':main()
