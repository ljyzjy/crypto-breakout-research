"""Reconstruct post-close big-candle labels and deduplicated capture rates."""
import hashlib,json,shutil,time
from decimal import Decimal
from pathlib import Path
import numpy as np,pandas as pd,psutil
H=Path(__file__).resolve().parent;I=H/'冻结输入';ROOT=H.parent.parent.parent;M=60_000;Q=15*M
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    f=json.loads((H/'冻结输入哈希.json').read_text(encoding='utf-8'));assert sha(H/'事后诊断方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    sources=json.loads((I/'minute_sources.json').read_text(encoding='utf-8'))['sources']
    comparison=json.loads((I/'comparison.json').read_text(encoding='utf-8'))['rows'];alllabels=[];summaries=[]
    for year in ('2024','2026'):
        events=pd.read_parquet(I/f'{year}_signal.parquet');assert events.observation_id.is_unique
        labels=[]
        for symbol,g in events.groupby('contract',sort=True):
            while psutil.virtual_memory().available<500*1024**2:
                if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
                time.sleep(3)
            item=sources[f'{year}_{symbol}'];file=Path(item['path']);assert sha(file)==item['sha256']
            d=pd.read_parquet(file,columns=['ts','open','high','low','close','volume','trade_count']).set_index('ts');assert d.index.is_unique
            for e in g.to_dict('records'):
                q=int(e['quarter_start']);side=int(e['market_allowed_side']);x=d.reindex(range(q-16*Q,q+Q,M))
                row={'observation_id':e['observation_id'],'contract':symbol,'quarter_start':q,'allowed_side':side,'status':'unknown','large':None}
                a=x[['open','high','low','close','volume','trade_count']].to_numpy(float)
                if len(x)!=255 or not np.isfinite(a).all() or not (a[:,:4]>0).all() or not (a[:,4:]>0).all():row['reason']='missing_or_nonpositive_minute';labels.append(row);continue
                if (a[:,1]<np.maximum.reduce([a[:,0],a[:,2],a[:,3]])).any() or (a[:,2]>np.minimum.reduce([a[:,0],a[:,1],a[:,3]])).any():
                    row['reason']='invalid_minute_ohlc';labels.append(row);continue
                hi=float(a[:-15,1].max());lo=float(a[:-15,2].min())
                if not np.isclose(hi,e['upper'],rtol=1e-9,atol=1e-12) or not np.isclose(lo,e['lower'],rtol=1e-9,atol=1e-12):
                    row['reason']='prior_boundary_mismatch';labels.append(row);continue
                assert side in (-1,1) and e['market_prior_status']=='allowed' and bool(e['long_known_eligible'] if side==1 else e['short_known_eligible'])
                op=float(a[-15,0]);close=float(a[-1,3]);change=Decimal(side)*(Decimal(str(close))-Decimal(str(op)))/Decimal(str(op))
                beyond=Decimal(side)*(Decimal(str(close))-Decimal(str(hi if side==1 else lo)))>0
                row.update({'status':'verified','reason':'ok','open':op,'high':float(a[-15:,1].max()),'low':float(a[-15:,2].min()),
                            'close':close,'volume':float(a[-15:,4].sum()),'trade_count':int(a[-15:,5].sum()),'upper':hi,'lower':lo,
                            'large':bool(change>=Decimal('0.01') and beyond)})
                labels.append(row)
            del d
        labels=pd.DataFrame(labels);assert labels.observation_id.is_unique and len(labels)==len(events);labels['source_year']=year
        alllabels.append(labels);bars=[]
        for (sym,q,side),g in labels.groupby(['contract','quarter_start','allowed_side']):
            if not g.status.eq('verified').all():bars.append({'contract':sym,'q':int(q),'side':int(side),'status':'unknown','ids':list(g.observation_id)});continue
            assert g.large.nunique()==1
            bars.append({'contract':sym,'q':int(q),'side':int(side),'status':'verified','large':bool(g.large.iloc[0]),'ids':list(g.observation_id)})
        nlarge=sum(b['status']=='verified' and b.get('large') for b in bars);unknown_label=sum(b['status']!='verified' for b in bars)
        for lev in (10,20):
            base=pd.read_parquet(I/f'{year}_baseline_ledger.parquet');retry=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
            for strategy in ('baseline','single_retest'):
                score=next(z for z in comparison if z['year']==year and z['leverage']==lev and z['strategy']==strategy)
                frames=[base] if strategy=='baseline' else [base,retry];ledger=pd.concat(frames,ignore_index=True)
                ledger=ledger[ledger.variant.eq(f'normal_2r_{lev}x')].set_index('observation_id')
                good=set(score['verified_observation_ids']);unknown=set(score['unknown_observation_ids']);captured=0;uncertain=0
                for bar in bars:
                    if bar['status']!='verified' or not bar['large']:continue
                    found=False
                    for obs in set(bar['ids'])&good:
                        r=ledger.loc[obs];assert isinstance(r,pd.Series)
                        if int(r.side)==bar['side'] and int(r.entry_ts)<bar['q']+Q:found=True;break
                    if found:captured+=1
                    elif set(bar['ids'])&unknown:uncertain+=1
                summaries.append({'year':year,'leverage':lev,'strategy':strategy,'candidate_events':len(events),'distinct_candidate_bars':len(bars),
                    'unknown_label_bars':unknown_label,'verified_large_bars':nlarge,'verified_captured_bars':captured,'unknown_capture_bars':uncertain,
                    'capture_pct':100*captured/nlarge if nlarge else None,'optimistic_capture_pct':100*(captured+uncertain)/nlarge if nlarge else None})
        print('CAPTURE53_PERIOD',year,'events',len(events),'bars',len(bars),'known_large',nlarge,'label_unknown',unknown_label,flush=True)
    data=pd.concat(alllabels,ignore_index=True);data.to_parquet(H/'跨期事后大柱标签.parquet',index=False)
    out={'rows':summaries,'label_statuses':data.status.value_counts().to_dict(),'label_sha256':sha(H/'跨期事后大柱标签.parquet'),
         'note':'Post-close descriptive labels over already-screened candidate bars; not market-wide recall or a trading feature.'}
    (H/'跨期大柱捕捉对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE53_RESULT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
