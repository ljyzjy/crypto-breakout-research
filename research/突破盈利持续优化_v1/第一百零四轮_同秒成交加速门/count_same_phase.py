"""Count raw trades in the current and 20 earlier same-phase one-second windows."""
from bisect import bisect_right
import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import sys
import zipfile
import pandas as pd
import requests

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def frozen():
    f=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in f['sources'].items():assert bulk.sha(path)==digest,path
    assert f['raw_batch_fingerprint']==bulk.fingerprint() and f['lookback_candles']==20 and f['threshold']=='40*N >= 3*P'
    return f


def fingerprint():
    return hashlib.sha256((bulk.sha(H/'研究冻结.json')+bulk.sha(Path(__file__))).encode()).hexdigest()


def archive(symbol,day):
    name=f'{symbol}-trades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/trades/{symbol}/{name}'
    ck=requests.get(url+'.CHECKSUM',timeout=(15,50));ck.raise_for_status();fields=ck.text.strip().split()
    assert len(fields)>=2 and Path(fields[1]).name==name;expected=fields[0].lower()
    roots=[bulk.runner.ROOT/'independent_raw_trade_samples',bulk.runner.ROOT/'raw_2022_full_trades',bulk.runner.ROOT/'same_phase_extra_raw']
    for folder in roots:
        p=folder/name
        if p.exists():assert bulk.sha(p)==expected;return p,{'day':day,'path':str(p),'sha256':expected,'bytes':p.stat().st_size,'url':url}
    folder=roots[-1];folder.mkdir(parents=True,exist_ok=True);dest=folder/name;partial=folder/(name+'.partial')
    assert dest.resolve().is_relative_to(bulk.runner.ROOT.resolve()) and partial.resolve().is_relative_to(folder.resolve())
    head=requests.head(url,timeout=(15,50));head.raise_for_status();size=int(head.headers['Content-Length']);assert 0<size<=800_000_000
    digest=hashlib.sha256();step=4*1024*1024;total=0
    with partial.open('wb') as out:
        for start in range(0,size,step):
            bulk.runner.guard();end=min(size-1,start+step-1)
            with requests.get(url,headers={'Range':f'bytes={start}-{end}'},stream=True,timeout=(15,60)) as response:
                response.raise_for_status();assert response.status_code==206 and response.headers.get('Content-Range')==f'bytes {start}-{end}/{size}'
                n=0
                for chunk in response.iter_content(256*1024):bulk.runner.guard();out.write(chunk);digest.update(chunk);n+=len(chunk)
                assert n==end-start+1;total+=n
    assert total==size and digest.hexdigest()==expected and bulk.sha(partial)==expected
    partial.replace(dest)
    return dest,{'day':day,'path':str(dest),'sha256':expected,'bytes':size,'url':url}


def count_windows(path,windows,guard=None):
    ordered=sorted((int(a),int(b),i) for i,(a,b) in enumerate(windows));starts=[x[0] for x in ordered]
    assert all(a<b for a,b,_ in ordered) and all(ordered[i-1][1]<=ordered[i][0] for i in range(1,len(ordered)))
    counts=[0]*len(windows)
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==1 and names[0].endswith('.csv')
        with io.TextIOWrapper(z.open(names[0]),encoding='utf-8-sig',newline='') as f:
            reader=csv.reader(f);first=next(reader)
            if first[0].strip().lower() in ('id','trade_id'):
                assert 'time' in first;time_index=first.index('time')
            else:
                assert len(first)==6;time_index=4;reader=itertools.chain([first],reader)
            for i,row in enumerate(reader):
                if guard and i%200000==0:guard()
                t=int(row[time_index]);idx=bisect_right(starts,t)-1
                if idx>=0:
                    start,end,original=ordered[idx]
                    if start<t<end:counts[original]+=1
    return counts


def run_event(s,fp):
    obs=s['observation_id'];work=bulk.runner.ROOT/'same_phase_2022_checkpoints';work.mkdir(parents=True,exist_ok=True)
    target=work/(hashlib.sha256((fp+'|'+obs).encode()).hexdigest()+'.json')
    if target.exists():
        saved=json.loads(target.read_text(encoding='utf-8'))
        assert saved['fingerprint']==fp and saved['observation_id']==obs
        if saved['status']!='unknown_source':return saved
    t=int(s['decision_ts']);windows=[(t-j*900000,t-j*900000+1000) for j in range(1,21)]+[(t,t+1000)]
    first=min(a for a,_ in windows);last=max(b for _,b in windows)
    days=pd.date_range(pd.Timestamp(first,unit='ms',tz='UTC').normalize(),pd.Timestamp(last-1,unit='ms',tz='UTC').normalize(),freq='D').strftime('%Y-%m-%d')
    total=[0]*21;metas=[]
    try:
        for day in days:
            path,meta=archive(s['contract'],day);metas.append(meta);part=count_windows(path,windows,bulk.runner.guard)
            total=[a+b for a,b in zip(total,part)]
        n,p=total[-1],sum(total[:-1]);stored=int(s['one_count'])
        if n!=stored:status='unknown_current_count_mismatch';accepted=None
        elif p==0:status='unknown_zero_history';accepted=None
        else:status='verified';accepted=40*n>=3*p
        result={'observation_id':obs,'contract':s['contract'],'decision_ts':t,'status':status,'current_n':n,'stored_n':stored,
                'previous_counts':total[:-1],'previous_total':p,'accepted':accepted,'archives':metas,'fingerprint':fp}
    except Exception as exc:
        if 'headroom' in str(exc):raise
        result={'observation_id':obs,'contract':s['contract'],'decision_ts':t,'status':'unknown_source',
                'error':type(exc).__name__+':'+str(exc)[:180],'archives':metas,'fingerprint':fp}
    tmp=target.with_suffix('.partial');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(target)
    return result


def main():
    bulk.runner.guard(start=True);frozen();test=json.loads((H/'严格秒窗合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==bulk.sha(Path(__file__)) and test['test_sha256']==bulk.sha(H/'test_windows.py')
    detail=pd.read_csv(R98/'候选状态与单位账本.csv');ids=set(detail.loc[detail.category.eq('trade'),'observation_id'])
    signals=pd.read_parquet(R98/'原始逐笔批次/逐笔信号.parquet');signals=signals[signals.observation_id.isin(ids)]
    assert len(signals)==len(ids)==133 and signals.observation_id.is_unique
    fp=fingerprint();records=[]
    for s in signals.sort_values(['contract','day','decision_ts']).to_dict('records'):
        bulk.runner.guard();r=run_event(s,fp);records.append(r)
        print('EXT104_EVENT',len(records),'/',len(signals),r['status'],s['contract'],s['day'],flush=True)
    out={'event_count':len(records),'events':records,'fingerprint':fp,'code_sha256':bulk.sha(Path(__file__)),
         'frozen_sha256':bulk.sha(H/'研究冻结.json'),'note':'Signal-time counts only; unverified sources and zero prior counts remain unknown.'}
    (H/'同秒计数结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT104_COUNTS_COMPLETE',len(records),flush=True)


if __name__=='__main__':main()
