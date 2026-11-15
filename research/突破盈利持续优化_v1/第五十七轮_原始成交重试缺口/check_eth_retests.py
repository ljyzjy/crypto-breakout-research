"""Strict public-source replay of two preselected ETH data-quality exceptions."""
import hashlib, io, json, math, shutil, sys, time, uuid
from pathlib import Path
import numpy as np, pandas as pd, psutil, requests

H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
OLD=ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation'
FIX=P/'第四十六轮_固定十一加密币跨时段'; RET=P/'第四十七轮_一次重新突破确认'
sys.path.insert(0,str(RET));import retest_decision, audit_retest_samples as audit
CASES=[('touch|ETHUSDT|1707902880000','4e81e34fe8570097ed261a5e8c09eb8e295551c4ddbbc7df9cc40a47192939ad.json'),
       ('touch|ETHUSDT|1719247620000','19381c46ac84d0f162d2880d1f8658eb056a0e3ea53ecac995cf61eb126d2d3e.json')]
BASE='https://data.binance.vision/data/futures/um/daily/'; M=60000; MAX_ROWS=500000
DROOT=Path('D:/').resolve()
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def fetch(kind,day,expected,trigger,end):
    while psutil.virtual_memory().available<850*1024**2:guard();time.sleep(3)
    guard();symbol='ETHUSDT';name=f'{symbol}-1m-{day}.zip' if kind=='klines' else f'{symbol}-{kind}-{day}.zip'
    url=BASE+(f'klines/{symbol}/1m/{name}' if kind=='klines' else f'{kind}/{symbol}/{name}')
    temp=(DROOT/f'CodexResearch_ETH57_{uuid.uuid4().hex}.zip').resolve()
    assert temp.parent==DROOT and not temp.exists()
    try:
        with requests.Session() as s:
            c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();claimed=c.text.strip().split()[0].lower()
            h=hashlib.sha256();size=0
            with s.get(url,headers={'Accept-Encoding':'identity'},stream=True,timeout=(15,120)) as response:
                response.raise_for_status()
                with temp.open('xb') as out:
                    for chunk in response.iter_content(chunk_size=256*1024):
                        guard()
                        if chunk:out.write(chunk);h.update(chunk);size+=len(chunk)
            if h.hexdigest()!=claimed or claimed!=expected['sha256'] or size!=expected['bytes']:
                raise ValueError('archive_changed:'+kind)
        if kind=='klines':
            frame=pd.read_csv(temp,compression='zip')
        else:
            colnames=(['agg_trade_id','price','quantity','transact_time','is_buyer_maker'] if kind=='aggTrades'
                      else ['id','price','qty','time','is_buyer_maker'])
            blocks=[];count=0
            for chunk in pd.read_csv(temp,compression='zip',usecols=colnames,dtype={'is_buyer_maker':str},chunksize=100000):
                guard();chunk=chunk.rename(columns={'id':'agg_trade_id','qty':'quantity','time':'transact_time'})
                t=chunk.transact_time.to_numpy('int64');selected=chunk.loc[(t>=trigger)&(t<end)]
                if len(selected):
                    count+=len(selected)
                    if count>MAX_ROWS:raise RuntimeError('event_window_exceeds_memory_cap')
                    blocks.append(selected)
            if not blocks:raise ValueError('missing_event_tape')
            frame=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        return frame,{'kind':kind,'url':url,'bytes':size,'sha256':claimed}
    finally:
        assert temp.parent==DROOT and temp.name.startswith('CodexResearch_ETH57_')
        if temp.exists():temp.unlink()
def flow(tape,t):
    w=tape[(tape.transact_time>t)&(tape.transact_time<t+5000)]
    maker=w.is_buyer_maker.astype(str).str.lower();v=w.price.to_numpy(float)*w.quantity.to_numpy(float)
    assert maker.isin(['true','false']).all() and np.isfinite(v).all() and (v>0).all()
    buy=float(v[maker.eq('false').to_numpy()].sum());sell=float(v[maker.eq('true').to_numpy()].sum())
    return len(w),buy,sell
def first(tape,e):
    x=tape[(tape.transact_time<int(e['trigger_minute'])+M)&((tape.price>e['upper'])|(tape.price<e['lower']))]
    assert len(x);r=x.iloc[0];return int(r.transact_time),float(r.price)
def run(obs,filename,candidates,baseline):
    oldpath=OLD/filename;old=json.loads(oldpath.read_text(encoding='utf-8'));assert old['status']=='verified'
    prior=next(r for r in old['rows'] if r['observation_id']==obs);o=prior['outcome']
    assert prior['resolution']=='raw_confirms_open_only' and o['status']=='flow_filter_not_met'
    cand=candidates[candidates.observation_id.eq(obs)];assert len(cand)==1;e=cand.iloc[0].to_dict()
    side=int(o['side']);spec=json.loads(e['long_spec'] if side==1 else e['short_spec'])
    assert bool(e['long_known_eligible' if side==1 else 'short_known_eligible'])
    assert e['market_prior_status']=='allowed' and int(e['market_allowed_side'])==side
    assert near(spec['level'],o['level']) and near(spec['stop_price'],o['stop_price'])
    assert side*(float(o['raw_entry_5s'])-float(spec['level']))<=0
    assert obs in baseline['unknown_observation_ids']
    expected={a['kind']:a for a in old['archives']};archives=[];trigger=int(e['trigger_minute']);end=int(e['quarter_end'])+M
    bars,meta=fetch('klines',e['day'],expected['klines'],trigger,end);archives.append(meta)
    bars=bars.set_index('open_time');times=list(range(int(e['quarter_start']),trigger+M,M))
    norm=pd.read_parquet(ROOT/'work'/'breakout_2024_11'/'normalized'/'ETHUSDT_klines.parquet').set_index('ts')
    cols=['open','high','low','close'];a=bars.reindex(times)[cols].to_numpy(float);b=norm.reindex(times)[cols].to_numpy(float)
    assert np.isfinite(a).all() and np.isfinite(b).all() and np.allclose(a,b,rtol=1e-9,atol=1e-12)
    if len(times)>1:assert not (a[:-1,1]>float(e['upper'])).any() and not (a[:-1,2]<float(e['lower'])).any()
    agg,meta=fetch('aggTrades',e['day'],expected['aggTrades'],trigger,end);archives.append(meta)
    raw,meta=fetch('trades',e['day'],expected['trades'],trigger,end);archives.append(meta)
    am=agg[agg.transact_time<trigger+M];rm=raw[raw.transact_time<trigger+M];bar=bars.loc[trigger]
    def ohlc(d):return [float(d.price.iloc[0]),float(d.price.max()),float(d.price.min()),float(d.price.iloc[-1])]
    av,rv=ohlc(am),ohlc(rm);off=[float(bar[k]) for k in cols]
    assert np.allclose(rv,off,rtol=1e-9,atol=1e-12) and not near(av[0],off[0]) and np.allclose(av[1:],off[1:],rtol=1e-9,atol=1e-12)
    count_name=next(k for k in ('count','number_of_trades','num_trades') if k in bar.index)
    quote_name=next(k for k in ('quote_volume','quote_asset_volume') if k in bar.index)
    assert len(rm)==int(bar[count_name]) and near(rm.quantity.sum(),bar['volume']) and near((rm.price*rm.quantity).sum(),bar[quote_name])
    ac,rc=first(agg,e),first(raw,e);assert ac==rc and ac==(int(o['decision_ts']),float(o['signal_close']))
    def reference(d):
        x=d[d.transact_time>=ac[0]+5000].iloc[0];return int(x.transact_time),float(x.price)
    ar,rr=reference(agg),reference(raw);assert ar==rr and ar==(int(o['entry_exec_ts']),float(o['raw_entry_5s']))
    af,rf=flow(agg,ac[0]),flow(raw,ac[0]);assert af[0]==int(o['five_count']) and af[0]>=3 and rf[0]>=3
    for i in (1,2):assert near(af[i],rf[i]) and near(af[i],(o['buy_notional'],o['sell_notional'])[i-1])
    base={**e,**o,**spec,'observation_id':obs};rawbase={**base,'five_count':rf[0],'buy_notional':rf[1],'sell_notional':rf[2]}
    rawbase['five_imbalance']=side*(rf[1]-rf[2])/(rf[1]+rf[2])
    left=retest_decision.decide(base,agg);right=retest_decision.decide(rawbase,raw)
    assert left['status']==right['status'] and left['status'] in ('no_retest_known','no_order_time','retest_flow_filter_not_met','known_risk_rejected','qualified')
    for key in ('side','first_decision_ts','retest_ts','decision_ts','signal_close','entry_exec_ts','raw_entry_5s','buy_notional','sell_notional','five_imbalance'):
        assert (key in left)==(key in right)
        if key in left:
            if key=='side' or key.endswith('_ts'):assert int(left[key])==int(right[key])
            else:assert near(left[key],right[key])
    if 'five_count' in left:assert left['five_count']>=3 and right['five_count']>=3
    if 'prechecks' in left:assert left['prechecks']==right['prechecks']
    if 'paths' in left:
        assert set(left['paths'])==set(right['paths'])
        for k in left['paths']:
            x,y=left['paths'][k],right['paths'][k]
            for field in ('status','entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','reason'):
                if isinstance(x[field],str):assert x[field]==y[field]
                elif field.endswith('_ts'):assert int(x[field])==int(y[field])
                else:assert near(x[field],y[field])
    n1=audit.replay(base,agg,left);n2=audit.replay(rawbase,raw,right);assert n1==n2
    noorder=left['status'] in ('no_retest_known','no_order_time','retest_flow_filter_not_met','known_risk_rejected')
    out={'all_checks_pass':True,'observation_id':obs,'archives':archives,'old_record_sha256':sha(oldpath),
         'plan_sha256':sha(H/'核验方案.md'),'audit_code_sha256':sha(Path(__file__)),'initial_reference':ar,
         'initial_flow_aggregate':af,'initial_flow_raw':rf,'raw_minute_count':len(rm),'official_minute_count':int(bar[count_name]),
         'aggregate_result':left,'raw_result':right,'independent_paths_checked_per_tape':n1,
         'sensitivity_status':'known_no_order' if noorder else 'qualified_paths_require_risk_settlement',
         'note':'Same-exchange raw vs aggregated prints; only single-event sensitivity, no actual execution.'}
    (H/(obs.split('|')[-1]+'逐笔复核.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('ETH57_CASE',obs,left['status'],out['sensitivity_status'],flush=True)
def main():
    test=json.loads((H/'重试窗口合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(Path(__file__)) and test['plan_sha256']==sha(H/'核验方案.md')
    frozen=json.loads((FIX/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'));source=FIX/'逐笔冻结输入'/'2024_candidates.parquet'
    assert sha(source)==frozen['inputs']['2024_candidates.parquet'];candidates=pd.read_parquet(source)
    results=json.loads((RET/'单次重试跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    baseline=next(x for x in results if x['year']=='2024' and x['leverage']==20 and x['strategy']=='single_retest')
    for obs,filename in CASES:
        target=H/(obs.split('|')[-1]+'逐笔复核.json')
        if target.exists():
            old=json.loads(target.read_text(encoding='utf-8'))
            if old['audit_code_sha256']==sha(Path(__file__)) and old['plan_sha256']==sha(H/'核验方案.md'):
                print('ETH57_CACHED',obs,old['sensitivity_status'],flush=True);continue
        run(obs,filename,candidates,baseline)
if __name__=='__main__':main()
