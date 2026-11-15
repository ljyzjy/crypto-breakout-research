"""Bounded public market-data recorder. No keys, account access, or exchange orders."""
import argparse,asyncio,gzip,json,time,math
from collections import Counter,deque
from pathlib import Path
import websockets
from prepare_data import ROOT,dump

class QuoteExecution:
    """Conservative top-of-book paper fill adapter, independent from historical OHLC."""
    def __init__(self,max_age_ms=2000):self.max_age_ms=max_age_ms;self.quotes={}
    def update(self,symbol,bid,ask,bid_qty,ask_qty,received_ms):
        if 0<bid<=ask and min(bid_qty,ask_qty)>=0:
            self.quotes[symbol]=(bid,ask,bid_qty,ask_qty,received_ms)
    def fill(self,symbol,side,qty,now_ms,ready_ms):
        q=self.quotes.get(symbol)
        if q is None or now_ms<ready_ms or now_ms-q[4]>self.max_age_ms:return None
        if q[4]<ready_ms or q[4]>now_ms:return None
        price,available=(q[1],q[3]) if side==1 else (q[0],q[2])
        if qty<=0 or available<qty:return None # no invented deeper liquidity or full-fill guarantee
        return {'symbol':symbol,'side':side,'qty':qty,'price':price,'received_ms':q[4],
                'fill_ms':now_ms,'kind':'top_of_book_paper_estimate','actual_exchange_fill':False}
    def trigger(self,symbol,side,stop,target,now_ms):
        q=self.quotes.get(symbol)
        if q is None or now_ms-q[4]>self.max_age_ms:return None
        executable=q[0] if side==1 else q[1]
        if (executable<=stop if side==1 else executable>=stop):return 'stop'
        if (executable>=target if side==1 else executable<=target):return 'target'
        return None

async def observe(duration=90,symbols=('BTCUSDT','ETHUSDT'),max_mb=128):
    folder=ROOT/'seconds';folder.mkdir(exist_ok=True)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    path=folder/(stamp+'-public-events.jsonl.gz')
    status={'mode':'public_observation_only','symbols':list(symbols),'started_ms':int(time.time()*1000),
      'duration_seconds':duration,'strategy_trading_enabled':False,'exchange_orders_sent':0,
      'scope':'BTC/ETH transport verification only; not live full-pool selection',
      'events':{},'connections':{},'errors':[],'status':'starting','file':path.name}
    counts=Counter();latencies=deque(maxlen=50000);last={};stop=asyncio.Event();bytes_written=0
    book=QuoteExecution()
    with gzip.open(path,'wt',encoding='utf-8') as out:
        async def stream(channel,streams):
            nonlocal bytes_written
            url=f'wss://fstream.binance.com/{channel}/stream?streams='+('/'.join(streams))
            tries=0
            while not stop.is_set() and tries<3:
                tries+=1
                try:
                    async with websockets.connect(url,open_timeout=15,ping_interval=20,ping_timeout=20,max_queue=4096) as ws:
                        status['connections'][channel]='connected'
                        async for raw in ws:
                            now=int(time.time()*1000);msg=json.loads(raw);d=msg.get('data',msg)
                            event=d.get('e','unknown');symbol=d.get('s','')
                            if symbol not in symbols:continue
                            record={'received_ms':now,'received_monotonic_ns':time.monotonic_ns(),'channel':channel,'data':d}
                            line=json.dumps(record,separators=(',',':'),ensure_ascii=False)+'\n';out.write(line)
                            bytes_written+=len(line.encode());counts[event]+=1;last[channel]=now
                            if isinstance(d.get('E'),int):latencies.append(now-d['E'])
                            if event=='bookTicker':
                                book.update(symbol,float(d['b']),float(d['a']),float(d['B']),float(d['A']),now)
                            if bytes_written>=max_mb*1024*1024:status['stop_reason']='size_cap';stop.set()
                            if stop.is_set():break
                except Exception as exc:
                    # Type only: never log proxy URLs, credentials or connection strings.
                    status['errors'].append({'channel':channel,'type':type(exc).__name__,'attempt':tries})
                    status['connections'][channel]='disconnected'
                    if not stop.is_set():await asyncio.sleep(min(tries,3))
            if tries>=3 and status['connections'].get(channel)!='connected':status['connections'][channel]='failed'
        async def report():
            while not stop.is_set():
                status.update(status='collecting',updated_ms=int(time.time()*1000),events=dict(counts),
                    raw_uncompressed_bytes=bytes_written,last_received_ms=last)
                dump(folder/'status.json',status);out.flush()
                await asyncio.sleep(1)
        tasks=[asyncio.create_task(stream('public',[s.lower()+'@bookTicker' for s in symbols])),
               asyncio.create_task(stream('market',[q for s in symbols for q in (s.lower()+'@aggTrade',s.lower()+'@kline_1m')])),
               asyncio.create_task(report())]
        try:await asyncio.wait_for(stop.wait(),timeout=duration)
        except asyncio.TimeoutError:status['stop_reason']='duration_complete'
        finally:
            stop.set()
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    import numpy as np
    status.update(status='completed',updated_ms=int(time.time()*1000),events=dict(counts),
        raw_uncompressed_bytes=bytes_written,compressed_bytes=path.stat().st_size,last_received_ms=last,
        observed_clock_difference_ms={'p50':float(np.percentile(latencies,50)),'p95':float(np.percentile(latencies,95)),
            'note':'Local receive minus exchange event timestamp; includes clock offset, not measured order latency.'} if latencies else None,
        transport_verified=counts['bookTicker']>0 and counts['aggTrade']>0,
        seconds_profitability_verified=False)
    dump(folder/'status.json',status)
    print(json.dumps({k:status[k] for k in ['status','events','transport_verified','errors']},ensure_ascii=False),flush=True)
    return status

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--duration',type=int,default=90)
    args=parser.parse_args();asyncio.run(observe(duration=max(5,min(args.duration,86400))))
