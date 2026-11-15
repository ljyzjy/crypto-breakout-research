"""Verify public daily archives and construct a causal previous-30-day liquidity ranking."""
import ast,concurrent.futures,hashlib,io,json,shutil,threading,time,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
WORK=ROOT/'work'/'point_in_time_universe30'/'daily';WORK.mkdir(parents=True,exist_ok=True)
DAY=86_400_000;BASE='https://data.binance.vision/';MIN_FREE=1_900_000_000
local=threading.local();PLAN=HERE/'日线处理规则.json'
# Preserve the archive checkpoints started before the ranking-only date-unit fix.
# Their archive parser, download routine, and frozen plan are verified below.
FINGERPRINT='66dc081041db35fde969b5e395b44cd8a043f818003fb3b2a7684ebc2090e71b'
ARCHIVE_AST='de2d1cf43323098c150d3d51e0f64a585d000c5db81242a22d77cfccc6774127'
PLAN_SHA='57eccd3a3a970708e2a9594762cf54a0da04db969d576db6750e74c35ec239b9'
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def parse(content,symbol,month):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names=z.namelist()
        if len(names)!=1 or not names[0].endswith('.csv'):raise ValueError('unexpected_zip_members')
        data=z.read(names[0]);first=data.splitlines()[0].decode('utf-8-sig')
    has_header=first.lower().startswith('open_time,')
    d=pd.read_csv(io.BytesIO(data),header=0 if has_header else None,names=None if has_header else COLS)
    required=['open_time','open','high','low','close','volume','close_time','quote_volume','count']
    if not set(required).issubset(d.columns):raise ValueError('unexpected_csv_columns')
    d=d[required].apply(pd.to_numeric,errors='raise')
    if not np.isfinite(d.to_numpy(float)).all() or d.open_time.duplicated().any():raise ValueError('nonfinite_or_duplicate')
    if (d.open_time%DAY!=0).any() or (d.close_time!=d.open_time+DAY-1).any():raise ValueError('unexpected_day_timestamps')
    month_id=pd.to_datetime(d.open_time,unit='ms',utc=True).dt.strftime('%Y-%m')
    if not month_id.eq(month).all():raise ValueError('out_of_month')
    priceok=(d[['open','high','low','close']]>0).all(axis=1)&d.high.ge(d[['open','low','close']].max(axis=1))&d.low.le(d[['open','high','close']].min(axis=1))
    volumeok=(d.volume>=0)&(d.quote_volume>=0)&(d['count']>=0)
    d['valid_for_ranking']=priceok&volumeok&(d.volume>0)&(d.quote_volume>0)&(d['count']>0)
    d['symbol']=symbol
    return d[['symbol','open_time','close_time','quote_volume','valid_for_ranking']].to_dict('records')
def task(record):
    symbol=record['symbol'];month=record['month'];key=record['key']
    ident=hashlib.sha256((FINGERPRINT+'|'+key+'|'+str(record['size'])+'|'+record['last_modified']).encode()).hexdigest()
    checkpoint=WORK/(ident+'.json')
    if checkpoint.exists():return json.loads(checkpoint.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        url=BASE+key;response=session().get(url+'.CHECKSUM',timeout=(15,50));response.raise_for_status()
        digest=response.text.strip().split()[0].lower()
        response=session().get(url,timeout=(15,80));response.raise_for_status();content=response.content
        if len(content)!=record['size']:raise ValueError('archive_size_changed_since_index')
        if hashlib.sha256(content).hexdigest()!=digest:raise ValueError('sha256_mismatch')
        rows=parse(content,symbol,month)
        out={'symbol':symbol,'month':month,'key':key,'status':'verified','sha256':digest,'rows':rows}
        temp=checkpoint.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(checkpoint)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'symbol':symbol,'month':month,'key':key,'status':'error','error':error,'rows':[]}
def build_ranks(d):
    schedules=[]
    for year,first,last,warm in [(2024,'2024-01-01','2024-06-29','2023-12-01'),
                                 (2026,'2026-05-01','2026-07-31','2026-04-01')]:
        grid=pd.date_range(warm,last,freq='D',tz='UTC');blocks=[]
        lo=int(grid[0].timestamp()*1000);hi=int((grid[-1]+pd.Timedelta(days=1)).timestamp()*1000)
        for symbol,g in d[(d.open_time>=lo)&(d.open_time<hi)].groupby('symbol'):
            # pandas 3 date_range defaults to microseconds, not nanoseconds.
            # Convert each UTC timestamp explicitly to the archive's milliseconds.
            grid_ms=np.asarray([int(day.timestamp()*1000) for day in grid],dtype=np.int64)
            z=g.set_index('open_time').reindex(grid_ms)
            value=z.quote_volume.where(z.valid_for_ranking.eq(True)).astype(float)
            q=value.shift(1).rolling(30,min_periods=30).sum()
            frame=pd.DataFrame({'symbol':symbol,'day':grid.strftime('%Y-%m-%d'),'past_30d_quote':q.to_numpy()})
            blocks.append(frame[frame.day.ge(first)&frame.past_30d_quote.notna()])
        if not blocks:continue
        x=pd.concat(blocks,ignore_index=True).sort_values(['day','past_30d_quote','symbol'],ascending=[True,False,True])
        x['eligible_symbols_that_day']=x.groupby('day').symbol.transform('size')
        x['rank']=x.groupby('day').cumcount()+1
        schedules.append(x[x['rank']<=20].assign(year=year))
    return pd.concat(schedules,ignore_index=True) if schedules else pd.DataFrame()
def main():
    tree=ast.parse(Path(__file__).read_text(encoding='utf-8'))
    archived=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('parse','task')]
    actual=hashlib.sha256(ast.dump(ast.Module(body=archived,type_ignores=[]),include_attributes=False).encode()).hexdigest()
    assert actual==ARCHIVE_AST and hashlib.sha256(PLAN.read_bytes()).hexdigest()==PLAN_SHA, 'archive cache contract changed'
    index=pd.read_parquet(HERE/'历史日线月档索引.parquet')
    quality=json.loads((HERE/'历史日线索引清点.json').read_text(encoding='utf-8'))
    assert len(index)==quality['archive_count'] and not index.duplicated(['symbol','month']).any()
    print('UNIVERSE30_DAILY_ARCHIVES',len(index),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        fs=[pool.submit(task,r) for r in index.to_dict('records')]
        for future in concurrent.futures.as_completed(fs):
            results.append(future.result())
            if len(results)%250==0:print('UNIVERSE30_DAILY',len(results),'/',len(index),flush=True)
    errors=[{k:r[k] for k in ['symbol','month','key','error']} for r in results if r['status']!='verified']
    rows=[z for r in results for z in r['rows']]
    d=pd.DataFrame(rows,columns=['symbol','open_time','close_time','quote_volume','valid_for_ranking'])
    assert not d.duplicated(['symbol','open_time']).any()
    d.to_parquet(HERE/'公开日线已校验成交额.parquet',index=False)
    ranks=build_ranks(d);ranks.to_parquet(HERE/'历史动态20币候选_仅数据排名.parquet',index=False)
    summary={'index_candidates':int(quality['usdt_name_candidates']),'indexed_archives':len(index),
             'verified_archives':sum(r['status']=='verified' for r in results),'archive_errors':errors,
             'daily_rows':len(d),'invalid_or_zero_activity_rows':int((~d.valid_for_ranking).sum()),
             'rank_days':int(ranks.day.nunique()),'selected_symbol_count':int(ranks.symbol.nunique()),
             'ranking_year_counts':ranks.groupby('year').size().to_dict(),
             'rank_day_eligible_range':[int(ranks.eligible_symbols_that_day.min()),int(ranks.eligible_symbols_that_day.max())],
             'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
             'index_sha256':hashlib.sha256((HERE/'历史日线月档索引.parquet').read_bytes()).hexdigest(),
             'note':'Top-20 is an archive-based candidate ranking, not verified past exchange tradability. Missing sources are not zero.'}
    (HERE/'历史动态币池数据质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_DAILY_COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
