"""Independent sample reaggregation, strict ranks, and candidate gate audit."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;H=3_600_000;M=60_000
def main():
    daily=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    bars=pd.read_parquet(HERE/'一分钟严格合成小时.parquet')
    top=pd.read_parquet(HERE/'分钟严格验证后动态池小时排名.parquet')
    events=pd.read_parquet(HERE/'历史动态池潜在触价_待逐笔验证.parquet')
    source=json.loads((HERE/'分钟档案及候选排除记录.json').read_text(encoding='utf-8'))
    quality=json.loads((HERE/'动态池分钟候选质量.json').read_text(encoding='utf-8'))
    assert quality['plan_sha256']==hashlib.sha256((HERE/'分钟候选生成方案.json').read_bytes()).hexdigest()
    assert quality['daily_rank_sha256']==hashlib.sha256((PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet').read_bytes()).hexdigest()
    by={(int(y),s):g.set_index('open_time') for (y,s),g in bars.groupby(['year','symbol'])}
    days=sorted(daily.day.unique());picks=sorted(set(np.linspace(0,len(days)-1,24,dtype=int).tolist()))
    rank_checks=0;excluded_hours=0
    for n,pos in enumerate(picks):
        day=days[pos];year=int(day[:4]);t=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)+((n*7)%24)*H
        universe=daily[daily.day.eq(day)];assert len(universe)==20
        expected=[];complete=True
        for r in universe.itertuples(index=False):
            d=by[(year,r.symbol)]
            cs=np.arange(t-25*H,t,H,dtype=np.int64);vs=np.array([t-H-k*24*H for k in range(21)],dtype=np.int64)
            z=d.reindex(np.unique(np.r_[cs,vs]))
            if not z.valid.fillna(False).all():complete=False;break
            closes=d.reindex(cs).close.to_numpy(float);ret=np.diff(np.log(closes));sd=ret.std(ddof=1)
            volume=d.reindex(vs).quote_volume.to_numpy(float);median=np.median(volume[1:])
            if sd<=0 or median<=0:complete=False;break
            score=float(ret[-6:].sum()/sd);rv=float(volume[0]/median)
            if rv>=1.5 and score!=0:expected.append({'symbol':r.symbol,'side':1 if score>0 else -1,
                                                       'daily_rank':int(r.rank),'score':score,'rvol':rv})
        actual=top[top.decision_hour.eq(t)]
        if not complete:
            excluded_hours+=1;assert actual.empty
        else:
            for side in (-1,1):
                x=sorted((e for e in expected if e['side']==side),key=lambda e:(-abs(e['score']),e['daily_rank'],e['symbol']))[:3]
                y=actual[actual.side.eq(side)].sort_values('hourly_rank')
                assert [e['symbol'] for e in x]==y.symbol.tolist(),('rank mismatch',day,side)
                for a,b in zip(x,y.itertuples(index=False)):
                    assert np.isclose(a['score'],b.score,rtol=1e-8,atol=1e-8)
                    assert np.isclose(a['rvol'],b.rvol,rtol=1e-8,atol=1e-8)
        rank_checks+=1
    top_lookup={(int(r.decision_hour),r.symbol,int(r.side)) for r in top.itertuples(index=False)}
    pool={(r.day,r.symbol) for r in daily.itertuples(index=False)}
    for r in events.itertuples(index=False):
        assert (r.day,r.symbol) in pool and r.quarter_start<=r.trigger_minute<r.quarter_end
        assert r.quarter_start==r.trigger_minute//(15*M)*(15*M)
        assert r.long_known_eligible or r.short_known_eligible
        for side,name in ((1,'long'),(-1,'short')):
            if getattr(r,name+'_known_eligible'):
                assert (int(r.trigger_minute)//H*H,r.symbol,side) in top_lookup
                d=json.loads(getattr(r,name+'_spec'));distance=side*(d['level']-d['stop_price'])
                assert distance>0 and distance<=1.5*r.atr and 2*distance/d['level']>=.006
                assert side*r.prior_body_atr>=.1
    records={(s['symbol'],int(s['year'])):s for s in source['symbol_sources']};session=requests.Session()
    samples=[]
    for symbol,year,month in [('BTCUSDT',2024,'2024-03'),('ORDIUSDT',2024,'2024-02'),
                              ('WLDUSDT',2024,'2024-03'),('BTCUSDT',2026,'2026-05'),('XAUUSDT',2026,'2026-05')]:
        record=records.get((symbol,year));a=next((x for x in record['archives'] if x['month']==month),None) if record else None
        if not a or a['status']!='verified':continue
        url='https://data.binance.vision/'+a['key'];check=session.get(url+'.CHECKSUM',timeout=(15,50));check.raise_for_status()
        sha=check.text.strip().split()[0].lower();response=session.get(url,timeout=(15,100));response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest()==sha==a['sha256']
        d=pd.read_csv(io.BytesIO(response.content),compression='zip')
        required=['open_time','open','high','low','close','volume','quote_volume'];assert set(required).issubset(d.columns)
        assert not d.open_time.duplicated().any()
        v=np.isfinite(d[required].to_numpy(float)).all(axis=1)&(d[['open','high','low','close','volume','quote_volume']].to_numpy(float)>0).all(axis=1)
        v&=(d.high>=d[['open','low','close']].max(axis=1))&(d.low<=d[['open','high','close']].min(axis=1))
        d['valid']=v;d['hour']=d.open_time//H*H
        g=d.sort_values('open_time').groupby('hour').agg(n=('open_time','size'),first=('open_time','first'),
          last=('open_time','last'),valid=('valid','all'),close=('close','last'),quote_volume=('quote_volume','sum'))
        g['valid']=g.valid&(g.n==60)&(g.first==g.index)&(g.last==g.index+59*M)
        start=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
        end=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        period=np.arange(start,end,H,dtype=np.int64);g=g.reindex(period)
        actual=by[(year,symbol)].reindex(period);expected_valid=g.valid.fillna(False).astype(bool)
        assert np.array_equal(expected_valid.to_numpy(),actual.valid.to_numpy(bool))
        good=expected_valid.to_numpy();assert np.allclose(g.close.to_numpy(float)[good],actual.close.to_numpy(float)[good],rtol=1e-10,atol=1e-10)
        assert np.allclose(g.quote_volume.to_numpy(float)[good],actual.quote_volume.to_numpy(float)[good],rtol=1e-9,atol=1e-6)
        samples.append({'year':year,'symbol':symbol,'month':month,'checked_hours':len(period),'valid_hours':int(good.sum()),'sha256':sha})
    out={'rank_decision_hours_sampled':rank_checks,'sampled_hours_rejected_for_incomplete_pool':excluded_hours,
         'all_output_candidates_checked':len(events),'minute_archive_samples':samples,
         'prior_btc_signal_parity':'see 分钟信号与原模型核验.json',
         'note':'These are candidate/data checks only; first tick direction, executable prices, risk, and account results remain unverified.'}
    (HERE/'动态分钟候选独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE32_AUDIT_PASS',json.dumps({k:v for k,v in out.items() if k!='minute_archive_samples'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
