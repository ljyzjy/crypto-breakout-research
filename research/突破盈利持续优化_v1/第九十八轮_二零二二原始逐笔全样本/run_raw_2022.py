"""Resumable original-trade replay; writes only to its own checkpoint and download folders."""
import hashlib
import json
from pathlib import Path
import sys
import time

import pandas as pd
import requests

H=Path(__file__).resolve().parent; P=H.parent; R90=P/'第九十轮_二零二二公开行情'; R93=P/'第九十三轮_原始逐笔抽样交叉核验'
sys.path.insert(0,str(R90)); import replay_2022 as runner
sys.path.insert(0,str(R93)); import compare_raw_aggregate as raw


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def frozen():
    doc=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in doc['sources'].items(): assert sha(path)==digest, path
    assert runner.fingerprint()==doc['source_fingerprint']
    return doc


def fingerprint():
    return hashlib.sha256(''.join(sha(x) for x in (H/'研究冻结.json',Path(__file__),R93/'compare_raw_aggregate.py')).encode()).hexdigest()


def download(symbol,day):
    name=f'{symbol}-trades-{day}.zip'; url=f'https://data.binance.vision/data/futures/um/daily/trades/{symbol}/{name}'
    response=requests.get(url+'.CHECKSUM',timeout=(15,50)); response.raise_for_status()
    parts=response.text.strip().split(); assert len(parts)>=2 and Path(parts[1]).name==name and len(parts[0])==64
    expected=parts[0].lower()
    existing=runner.ROOT/'independent_raw_trade_samples'/name
    folder=runner.ROOT/'raw_2022_full_trades'; folder.mkdir(parents=True,exist_ok=True)
    dest=existing if existing.exists() else folder/name
    assert dest.resolve().is_relative_to(runner.ROOT.resolve())
    if dest.exists(): assert sha(dest)==expected
    else:
        partial=dest.with_suffix('.zip.partial'); digest=hashlib.sha256(); size=0
        with requests.get(url,stream=True,timeout=(15,120)) as req:
            req.raise_for_status()
            with partial.open('wb') as f:
                for chunk in req.iter_content(256*1024):
                    runner.guard(); size+=len(chunk)
                    if size>800_000_000: raise RuntimeError('raw_archive_size_cap')
                    f.write(chunk); digest.update(chunk)
        assert digest.hexdigest()==expected
        partial.replace(dest)
    return dest,{'kind':'trades','day':day,'sha256':expected,'bytes':dest.stat().st_size,'path':str(dest),'url':url}


def tape_for(e, archive_by_day):
    lo=int(e['trigger_minute']); hi=int(e['quarter_end'])+60000
    days=pd.date_range(pd.Timestamp(lo,unit='ms',tz='UTC').normalize(),pd.Timestamp(hi-1,unit='ms',tz='UTC').normalize(),freq='D').strftime('%Y-%m-%d')
    rows=[]
    for day in days:
        path=archive_by_day[day][0]
        rows.extend(raw.read_window(path,'trades',lo,hi))
    rows.sort(key=lambda r:(r[0],r[1]))
    return pd.DataFrame([(a,b,float(c),float(d),f) for a,b,c,d,f in rows],columns=['transact_time','agg_trade_id','price','quantity','is_buyer_maker'])


def execute(fp,symbol,day,events):
    work=runner.ROOT/'raw_2022_full_checkpoints'; work.mkdir(parents=True,exist_ok=True)
    target=work/(runner.key(fp,symbol,day,events)+'.json')
    if target.exists():
        old=json.loads(target.read_text(encoding='utf-8'))
        assert old['status']=='verified' and old['fingerprint']==fp
        assert {x['observation_id'] for x in old['rows']}=={x['observation_id'] for x in events}
        return old
    original=runner.WORK/(runner.key(runner.fingerprint(),symbol,day,events)+'.json')
    cp=json.loads(original.read_text(encoding='utf-8')); assert cp['status']=='verified' and cp['fingerprint']==runner.fingerprint()
    prior={x['observation_id']:x for x in cp['rows']}
    body,bar_meta=runner.minutes.archive('klines',symbol,day)
    expected=next(a for a in cp['archives'] if a['kind']=='klines' and a['day']==day)
    assert bar_meta['sha256']==expected['sha256']
    bars=runner.minute_bars(body,day); del body
    blocked={'daily_monthly_ohlc_mismatch','market_source_unknown'}
    eligible=[e for e in events if prior[e['observation_id']]['status'] not in blocked]
    archive_by_day={}
    for e in eligible:
        lo=int(e['trigger_minute']); hi=int(e['quarter_end'])+60000
        dates=pd.date_range(pd.Timestamp(lo,unit='ms',tz='UTC').normalize(),pd.Timestamp(hi-1,unit='ms',tz='UTC').normalize(),freq='D').strftime('%Y-%m-%d')
        for date in dates:
            if date not in archive_by_day: archive_by_day[date]=download(symbol,date)
    records=[]
    for e in events:
        obs=e['observation_id']; previous=prior[obs]['status']
        if previous in blocked:
            result={'status':previous}
        else:
            tape=tape_for(e,archive_by_day)
            result=runner.engine.decide(e,tape,bars) if len(tape) else {'status':'missing_event_tape'}
            del tape
        records.append({'observation_id':obs,**result})
    out={'status':'verified','fingerprint':fp,'contract':symbol,'day':day,'original_checkpoint_sha256':sha(original),
         'archives':[bar_meta]+[x[1] for x in archive_by_day.values()],'rows':records}
    runner.guard(); tmp=target.with_suffix('.partial'); tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8'); tmp.replace(target)
    return out


def main():
    runner.guard(start=True); config=frozen(); fp=fingerprint()
    data=pd.read_parquet(R90/'候选数据/固定十一币双币过滤潜在触价.parquet')
    groups=[(sym,day,g.to_dict('records')) for (sym,day),g in data.groupby(['contract','day'],sort=True)]
    assert len(data)==config['candidate_count'] and len(groups)==config['group_count']
    done=0; errors=[]
    print('EXT98_START',len(groups),len(data),flush=True)
    for sym,day,events in groups:
        error=''
        for attempt in range(3):
            try:
                runner.guard(); out=execute(fp,sym,day,events); error=''; break
            except Exception as exc:
                error=type(exc).__name__+':'+str(exc)[:160]
                if any(x in error for x in ('headroom','size_cap','window_exceeds')): break
                if attempt<2: time.sleep(attempt+1)
        if error: errors.append({'symbol':sym,'day':day,'error':error})
        else: done+=1
        print('EXT98_GROUP',done,'/',len(groups),'errors',len(errors),sym,day,error or 'verified',flush=True)
        progress={'candidate_count':len(data),'group_count':len(groups),'completed_groups':done,'errors':errors,
                  'fingerprint':fp,'note':'Checkpoint progress only. Risk settlement, independent replay and final metrics are not complete.'}
        (H/'原始逐笔回放进度.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')
        if error and 'headroom' in error: break
    print('EXT98_STOP',done,'/',len(groups),'errors',len(errors),flush=True)


if __name__=='__main__':main()
