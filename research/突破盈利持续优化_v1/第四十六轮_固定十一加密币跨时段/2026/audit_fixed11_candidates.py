"""Check every gate and rederive four 2023 event features from official daily 1m."""
import hashlib,io,json,sys,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;P=H.parent.parent;M=60_000;Q=15*M
sys.path.insert(0,str(P/'第四十轮_BTC_ETH事前活跃度'))
from market_decisions import classify
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def readzip(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
    return pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
def main():
    d=pd.read_parquet(H/'固定十一币双币过滤潜在触价.parquet');top=pd.read_parquet(H/'固定十一币已知小时排名.parquet')
    market=pd.read_parquet(H/'BTC_ETH一分钟合成十五分钟.parquet')
    lookup={(r['symbol'],int(r['open_time'])):r for r in market.to_dict('records')}
    ranks={(int(r.decision_hour),r.symbol,int(r.side)):r for r in top.itertuples(index=False)}
    assert d.observation_id.is_unique and not d.duplicated(['symbol','quarter_start']).any()
    for e in d.itertuples(index=False):
        assert e.quarter_start==e.trigger_minute//Q*Q and e.quarter_start<=e.trigger_minute<e.quarter_end
        state=classify(int(e.quarter_start),lookup,set());assert state['market_status']==e.market_prior_status
        assert state['market_status']=='allowed' and state['allowed_side']==e.market_allowed_side
        assert e.long_known_eligible or e.short_known_eligible
        for side,name in ((1,'long'),(-1,'short')):
            if getattr(e,name+'_known_eligible'):
                assert side==state['allowed_side'];rank=ranks.get((int(e.trigger_minute)//(60*M)*(60*M),e.symbol,side));assert rank is not None
                z=json.loads(getattr(e,name+'_spec'));distance=side*(z['level']-z['stop_price'])
                assert z['rank']==int(rank.hourly_rank) and z['liquidity_rank']==int(rank.liquidity_rank)
                assert distance>0 and distance<=1.5*e.atr and 2*distance/z['level']>=.006 and side*e.prior_body_atr>=.1
    qs=sorted(set(map(int,d.quarter_start)))
    for q in qs:
        before=classify(q,lookup,set());saved={}
        for sym in ('BTCUSDT','ETHUSDT'):
            for t in (q,q+Q):
                k=(sym,t);saved[k]=lookup.get(k);lookup[k]={'count':99999999,'open':1.,'close':10**8,'volume':1.}
        assert classify(q,lookup,set())==before
        for k,v in saved.items():
            if v is None:del lookup[k]
            else:lookup[k]=v
    z=d.copy();z['minute_of_day']=(z.trigger_minute//M)%1440
    picks=[]
    for cohort in ('opening','touch'):
        g=z[z.cohort.eq(cohort)&z.minute_of_day.ge(360)].sort_values(['trigger_minute','symbol'])
        if len(g):picks.extend([g.iloc[0],g.iloc[-1]])
    assert len(picks)==4
    samples=[];session=requests.Session()
    for e in picks:
        name=f'{e.contract}-1m-{e.day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/klines/{e.contract}/1m/{name}'
        c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
        r=session.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
        b=readzip(r.content).set_index('open_time').sort_index();start=int(e.quarter_start)-21*Q
        times=np.arange(start,int(e.trigger_minute)+M,M,dtype=np.int64);window=b.reindex(times)
        cols=['open','high','low','close','volume','quote_volume','count'];assert np.isfinite(window[cols].to_numpy(float)).all()
        def quarter(q):
            a=b.reindex(np.arange(q,q+Q,M,dtype=np.int64));assert len(a)==15 and np.isfinite(a[cols].to_numpy(float)).all()
            return {'open':float(a.open.iloc[0]),'high':float(a.high.max()),'low':float(a.low.min()),'close':float(a.close.iloc[-1]),'count':float(a['count'].sum())}
        q=int(e.quarter_start);prev=[quarter(q-k*Q) for k in range(21,0,-1)]
        upper=max(x['high'] for x in prev[-16:]);lower=min(x['low'] for x in prev[-16:]);tr=[]
        for j in range(7,21):
            x=prev[j];pc=prev[j-1]['close'];tr.append(max(x['high']-x['low'],abs(x['high']-pc),abs(x['low']-pc)))
        atr=float(np.mean(tr))
        if e.cohort=='opening':pace=prev[-1]['count']/np.mean([x['count'] for x in prev[:-1]]);body=(prev[-1]['close']-prev[-1]['open'])/atr
        else:
            k=int((int(e.trigger_minute)-q)//M);current=b.reindex(np.arange(q,int(e.trigger_minute),M,dtype=np.int64))
            hist=[float(b.reindex(np.arange(q-i*Q,q-i*Q+k*M,M,dtype=np.int64))['count'].sum()) for i in range(20,0,-1)]
            pace=float(current['count'].sum())/np.mean(hist);body=(float(current.close.iloc[-1])-float(current.open.iloc[0]))/atr
        for name,value in [('upper',upper),('lower',lower),('atr',atr),('prior_prefix_ratio',pace),('prior_body_atr',body)]:
            assert np.isclose(float(e[name]),value,rtol=1e-9,atol=1e-10),(e.observation_id,name)
        pre=b.loc[int(e.trigger_minute)-M];bar=b.loc[int(e.trigger_minute)]
        assert float(bar.high)>upper or float(bar.low)<lower
        for side,name in ((1,'long'),(-1,'short')):
            if bool(e[name+'_known_eligible']):
                sp=json.loads(e[name+'_spec']);stop=float(pre.low-.1*atr if side==1 else pre.high+.1*atr)
                assert np.isclose(sp['stop_price'],stop,rtol=1e-9,atol=1e-10)
        samples.append({'observation_id':e.observation_id,'daily_minute_sha256':sha})
        print('FIXED11_46_EVENT_SAMPLE_2026',len(samples),'/4',flush=True)
    out={'all_candidate_gates_checked':len(d),'market_quarters_future_perturbed':len(qs),
         'independent_daily_minute_samples':len(samples),'samples':samples,'all_checks_pass':True,
         'note':'Source sample checks and causal gates only; first tick and unit PnL not yet established.'}
    (H/'固定十一币候选独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_EVENT_AUDIT_2026',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
