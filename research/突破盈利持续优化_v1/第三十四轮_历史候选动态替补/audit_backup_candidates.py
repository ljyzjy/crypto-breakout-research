"""Audit all backup candidate gates and independently recompute sample candle features."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;M=60_000;Q=15*M
def main():
    d=pd.read_parquet(HERE/'替补动态池潜在触价_待逐笔验证.parquet')
    top=pd.read_parquet(HERE/'逐小时动态替补排名_待候选验证.parquet')
    old=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    lookup={(int(r.decision_hour),r.symbol,int(r.side)):r for r in top.itertuples(index=False)}
    prior={(int(r.year),r.day,r.symbol) for r in old.itertuples(index=False)}
    assert d.observation_id.is_unique and not d.duplicated(['symbol','quarter_start']).any()
    for e in d.itertuples(index=False):
        assert e.quarter_start==e.trigger_minute//Q*Q and e.quarter_start<=e.trigger_minute<e.quarter_end
        assert e.long_known_eligible or e.short_known_eligible
        for side,name in ((1,'long'),(-1,'short')):
            if getattr(e,name+'_known_eligible'):
                rank=lookup.get((int(e.trigger_minute)//(60*M)*(60*M),e.symbol,side));assert rank is not None
                z=json.loads(getattr(e,name+'_spec'));dist=side*(z['level']-z['stop_price'])
                assert z['rank']==int(rank.hourly_rank) and z['available_pool_rank']==int(rank.eligible_pool_rank)
                assert dist>0 and dist<=1.5*e.atr and 2*dist/z['level']>=.006 and side*e.prior_body_atr>=.1
    z=d.copy();z['new_symbol_day']=[(int(r.source_year),r.day,r.symbol) not in prior for r in z.itertuples(index=False)]
    z['minute_of_day']=(z.trigger_minute//M)%1440;eligible=z[z.minute_of_day.ge(360)].sort_values(['source_year','trigger_minute','symbol'])
    picks=[]
    for year,cohort in [('2024','opening'),('2024','touch'),('2026','opening'),('2026','touch')]:
        g=eligible[eligible.source_year.eq(year)&eligible.cohort.eq(cohort)&eligible.new_symbol_day]
        if g.empty:g=eligible[eligible.source_year.eq(year)&eligible.cohort.eq(cohort)]
        if len(g):picks.append(g.iloc[0])
    samples=[];session=requests.Session()
    for e in picks:
        name=f'{e.contract}-1m-{e.day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/klines/{e.contract}/1m/{name}'
        c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
        response=session.get(url,timeout=(15,90));response.raise_for_status();assert hashlib.sha256(response.content).hexdigest()==sha
        b=pd.read_csv(io.BytesIO(response.content),compression='zip').set_index('open_time').sort_index()
        start=int(e.quarter_start)-21*Q;times=np.arange(start,int(e.trigger_minute)+M,M,dtype=np.int64);window=b.reindex(times)
        cols=['open','high','low','close','volume','quote_volume','count'];assert np.isfinite(window[cols].to_numpy(float)).all()
        def quarter(q):
            a=b.reindex(np.arange(q,q+Q,M,dtype=np.int64));assert len(a)==15 and np.isfinite(a[cols].to_numpy(float)).all()
            return {'open':float(a.open.iloc[0]),'high':float(a.high.max()),'low':float(a.low.min()),'close':float(a.close.iloc[-1]),'count':float(a['count'].sum())}
        qstart=int(e.quarter_start);prev=[quarter(qstart-k*Q) for k in range(21,0,-1)]
        upper=max(x['high'] for x in prev[-16:]);lower=min(x['low'] for x in prev[-16:]);trs=[]
        for j in range(7,21):
            x=prev[j];pc=prev[j-1]['close'];trs.append(max(x['high']-x['low'],abs(x['high']-pc),abs(x['low']-pc)))
        atr=float(np.mean(trs))
        if e.cohort=='opening':
            pace=prev[-1]['count']/np.mean([x['count'] for x in prev[-21:-1]])
            body=(prev[-1]['close']-prev[-1]['open'])/atr
        else:
            k=int((int(e.trigger_minute)-qstart)//M);assert k>0
            current=b.reindex(np.arange(qstart,int(e.trigger_minute),M,dtype=np.int64));count=float(current['count'].sum())
            hist=[]
            for q in range(20,0,-1):hist.append(float(b.reindex(np.arange(qstart-q*Q,qstart-q*Q+k*M,M,dtype=np.int64))['count'].sum()))
            pace=count/np.mean(hist);body=(float(current.close.iloc[-1])-float(current.open.iloc[0]))/atr
        for key,expected in [('upper',upper),('lower',lower),('atr',atr),('prior_prefix_ratio',pace),('prior_body_atr',body)]:
            assert np.isclose(float(e[key]),expected,rtol=1e-9,atol=1e-10),(e.observation_id,key,float(e[key]),expected)
        before=b.loc[int(e.trigger_minute)-M];bar=b.loc[int(e.trigger_minute)]
        assert float(bar.high)>upper or float(bar.low)<lower
        for side,name in ((1,'long'),(-1,'short')):
            if bool(e[name+'_known_eligible']):
                spec=json.loads(e[name+'_spec']);expected=float(before.low-.1*atr if side==1 else before.high+.1*atr)
                assert np.isclose(spec['stop_price'],expected,rtol=1e-9,atol=1e-10)
        samples.append({'observation_id':e.observation_id,'new_symbol_day':bool(e.new_symbol_day),'archive_sha256':sha})
    out={'all_candidate_gates_checked':len(d),'independent_1m_feature_samples':len(samples),'samples':samples,
         'note':'Minute checks only; tick ordering, execution and account profitability require separate verification.'}
    (HERE/'替补动态候选独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_CANDIDATE_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
