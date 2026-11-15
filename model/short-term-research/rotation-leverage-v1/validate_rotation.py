import hashlib,json
from datetime import datetime,timezone
import pandas as pd
import rotation_engine as e

def main():
    frozen=e.base.read(e.ROOT/'frozen.json')
    for name,h in frozen.items():assert hashlib.sha256((e.ROOT/name).read_bytes()).hexdigest()==h,name
    m=e.manifest()
    for name,h in m['old_hashes'].items():assert hashlib.sha256((e.RESEARCH/name).read_bytes()).hexdigest()==h,name
    for name,v in m['processed'].items():assert hashlib.sha256((e.ROOT/name).read_bytes()).hexdigest()==v['sha256'],name
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==268
    checks=['All frozen sources,new processeddata andold snapshots match recordedhashes'];total=0
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'));active=set()
        for o in r['orders']:
            assert o['cash']>=-1e-7
            if o['side']=='buy':
                assert o['symbol'] not in active and len(active)<2;active.add(o['symbol'])
                assert o['ts']==o['information_ts']+r['delay_minutes']*60
                info=pd.Timestamp(o['information_ts'],unit='s',tz='UTC');assert info.hour==0 and info.minute==0
                tr=next(t for t in r['selection_trace'] if t['date']==info.strftime('%Y-%m-%d'));assert o['symbol'] in tr['selected']
                assert pd.Timestamp(tr['information_through'],tz='UTC')+pd.Timedelta(days=1)<=info
            else:assert o['symbol'] in active;active.remove(o['symbol'])
        for t in r['trades']:
            assert abs(t['notional']-t['margin']*r['leverage'])<1e-8
            assert t['margin']<=200 and abs(t['qty']*t['entry_price']-t['notional'])<1e-8
            assert abs(t['fees']-r['fee']*t['qty']*(t['entry_price']+t['exit_price']))<1e-8
            assert abs(t['gross_pnl']-t['fees']-t['slippage']-t['funding']-t['pnl'])<1e-8
            if r['mode']=='delayed_retry' and t['reason'] in ('gap_stop','stop_loss') and t['pnl']<0:
                mid=pd.Timestamp(t['exit_ts'],unit='s',tz='UTC').normalize();end=int((mid+pd.Timedelta(days=7-mid.weekday())).timestamp())
                assert not any(o['side']=='buy' and o['symbol']==t['symbol'] and t['exit_ts']<=o['ts']<end for o in r['orders'])
            total+=1
        if r['valid_for_comparison']:
            assert not active and abs(1000+sum(t['pnl'] for t in r['trades'])-r['final_equity'])<1e-7
            assert abs(r['funding_cost']-sum(f['payment'] for f in r['funding_events']))<1e-7
            if r['venue']=='perp':assert r['minimum_collateral_ratio_pct'] is None or r['minimum_collateral_ratio_pct']>7
        else:
            assert r['return_pct'] is None and r['annualized_return_pct'] is None and r['data_issues']
        if r['mode']=='rank_buffer':
            for i,tr in enumerate(r['selection_trace']):
                expected=e.retained_selection(tr['ranked'],tr['held_before_decision']) if i==0 or pd.Timestamp(tr['date']).weekday()==0 else r['selection_trace'][i-1]['selected']
                assert tr['selected']==expected
        if r['venue']=='spot' and r['mode'] in ('slow_base','btc_eth'):
            if r['mode']=='slow_base':old=e.prior.cached_run(r['start'],r['end'],'pool_slow_selection',r['fee'],r['resolution'],r['delay_minutes'])
            else:old=e.prior.old.c.cached_run(r['start'],r['end'],'vol_target200',r['fee'],r['resolution'],r['delay_minutes'],('BTCUSDT','ETHUSDT'))
            for field in ('return_pct','max_drawdown','fees','slippage_cost','mean_exposure_pct'):assert abs(r[field]-old[field])<1e-8,(r['id'],field)
    checks.append(f'All268 scenarios audited: {total} completed scenario-trades; cash,max2positions,knownsignals,buffer,weeklyretry,margin/notional,costs,funding andhalt suppression verified')
    checks.append('All14 existing slowbaseline/BTCETH spotcontrols reproduce previous economicmetrics acrossfee,delay,year,resolution')
    prefixes=[]
    for venue in ('spot','perp'):
        for mode in ('rank_buffer','delayed_retry'):
            full=e.cached_run('2025-01-01','2026-10-31',mode,venue)
            for end in ('2025-06-30','2026-06-30'):
                short=e.simulate('2025-01-01',end,mode,venue)
                bound=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
                filt=lambda r:[o for o in r['orders'] if o['ts']<bound and o['reason']!='window_end']
                a,b=filt(short),filt(full);assert len(a)==len(b)
                for x,y in zip(a,b):
                    for k in ('side','symbol','ts','information_ts','reason'):assert x[k]==y[k],(venue,mode,end,k)
                    for k in ('cash','qty','price'):assert abs(x[k]-y[k])<1e-8,(venue,mode,end,k)
                assert short['selection_trace']==[r for r in full['selection_trace'] if r['date']<=end]
                prefixes.append({'venue':venue,'mode':mode,'end':end,'passed':True,'orders':len(a)})
                print('prefix passed',venue,mode,end,flush=True)
    checks.append('Two actual-data future truncations preservepriorselectedsets andorders forbothnewvariants onspot/perpetual1x; administrativewindowclose excluded')
    result={'passed':True,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scenarios':268,'scenario_trades':total,'checks':checks,'prefixes':prefixes,'preflight':e.base.read(e.ROOT/'preflight-validation.json'),'limits':['Historical data already explored; not independent holdout.','Historical exactMMR/liquidationfees not reconstructed.7percentbarrier isconservative stress assumption.','Missingfunding/heldmark/executionpath aborts andno fullperiodreturnisreported.','15percentdrawdown ishistoricalexecutionclose criterion; intrabarpressure separatelyreported.']}
    e.base.dump(e.ROOT/'validation.json',result);print(json.dumps({'passed':True,'scenarios':268,'trades':total,'prefix_checks':len(prefixes)}))

if __name__=='__main__':main()
