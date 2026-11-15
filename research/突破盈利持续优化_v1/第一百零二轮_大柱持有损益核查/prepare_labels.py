"""Build ex-post completed-candle labels, requiring matching official daily OHLC."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R100=P/'第一百轮_突破无进展提前退出';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def frozen():
    f=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in f['sources'].items():assert bulk.sha(path)==digest,path
    assert f['raw_batch_fingerprint']==bulk.fingerprint()


def main():
    bulk.runner.guard(start=True);frozen()
    proof=json.loads((R100/'进展退出汇总独立核验.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['result_sha256']==bulk.sha(R100/'进展退出结果汇总.json')
    ledger=pd.read_parquet(R100/'进展退出单位账本.parquet');eligible=ledger[ledger.risk_status.eq('verified')&~ledger.liq_proxy.fillna(True).astype(bool)].observation_id.unique()
    signals=pd.read_parquet(R98/'原始逐笔批次/逐笔信号.parquet').set_index('observation_id').loc[eligible].reset_index()
    assert signals.observation_id.is_unique
    supplements=json.loads((bulk.R90/'二零二二日档补源质量.json').read_text(encoding='utf-8'))
    sources={x['symbol']:x for x in supplements['selected_sources']};records=[];archives=[]
    archive_dir=bulk.runner.ROOT/'raw_candle_daily_recheck';archive_dir.mkdir(parents=True,exist_ok=True)
    for symbol,g in signals.groupby('contract',sort=True):
        source=sources[symbol];assert bulk.sha(source['path'])==source['sha256']
        norm=pd.read_parquet(source['path'],columns=['ts','open','high','low','close','volume','quote_volume','trade_count']).set_index('ts')
        for day,part in g.groupby('day',sort=True):
            bulk.runner.guard();meta=None;daily=None
            try:
                body,meta=bulk.runner.minutes.archive('klines',symbol,day)
                assert hashlib.sha256(body).hexdigest()==meta['sha256']
                dest=archive_dir/f'{symbol}-1m-{day}.zip';assert dest.resolve().is_relative_to(archive_dir.resolve())
                if dest.exists():assert bulk.sha(dest)==meta['sha256']
                else:
                    tmp=dest.with_suffix('.zip.partial');tmp.write_bytes(body);assert bulk.sha(tmp)==meta['sha256'];tmp.replace(dest)
                daily=bulk.runner.minute_bars(body,day);archives.append({'contract':symbol,'day':day,'path':str(dest),'sha256':meta['sha256']})
            except Exception as exc:
                if 'headroom' in str(exc):raise
                meta={'error':type(exc).__name__+':'+str(exc)[:160]}
            for s in part.to_dict('records'):
                obs=s['observation_id'];q=int(s['quarter_start']);side=int(s['side']);atr=D(str(s['atr']));times=range(q,q+15*60000,60000)
                item={'observation_id':obs,'contract':symbol,'day':day,'quarter_start':q,'side':side,'atr':str(atr),'status':'unknown_invalid_normalized'}
                bar=norm.reindex(times);x=bar[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
                if len(bar)==15 and np.isfinite(x).all() and (x>0).all() and atr>0:
                    if daily is None:item.update(status='unknown_daily_source',error=meta['error'])
                    else:
                        a=bar[['open','high','low','close']].to_numpy(float);b=daily.reindex(times)[['open','high','low','close']].to_numpy(float)
                        if not np.isfinite(b).all() or not np.allclose(a,b,rtol=1e-9,atol=1e-12):item['status']='unknown_daily_ohlc_mismatch'
                        else:
                            open_=D(str(bar.open.iloc[0]));close=D(str(bar.close.iloc[-1]));large=D(side)*(close-open_)>=atr
                            item.update(status='verified',quarter_open=str(open_),quarter_close=str(close),large_aligned=bool(large))
                records.append(item)
            print('EXT102_SOURCE',len(records),'/',len(signals),symbol,day,flush=True)
    assert len(records)==len(signals)
    labels=pd.DataFrame(records);labels.to_parquet(H/'事后大柱标签.parquet',index=False)
    quality={'label_count':len(labels),'statuses':labels.status.value_counts().to_dict(),'archives':archives,
             'label_sha256':bulk.sha(H/'事后大柱标签.parquet'),'code_sha256':bulk.sha(Path(__file__)),
             'frozen_sha256':bulk.sha(H/'研究冻结.json'),'note':'Completed-candle labels are assessment only, never entry features.'}
    (H/'大柱标签质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT102_LABELS',quality['statuses'],flush=True)


if __name__=='__main__':main()
