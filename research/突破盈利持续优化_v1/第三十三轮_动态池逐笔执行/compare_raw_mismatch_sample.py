"""Test the frozen raw/aggregate reconciliation protocol on the reported ADA case."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
from tape_decision import decide
from leveraged_paths import simulate_path
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
SYMBOL='ADAUSDT';DAY='2024-03-04';MINUTE=1_709_532_900_000;M=60_000
BASE='https://data.binance.vision/data/futures/um/daily/'
def fetch(kind):
    key=f'klines/{SYMBOL}/1m/{SYMBOL}-1m-{DAY}.zip' if kind=='klines' else f'{kind}/{SYMBOL}/{SYMBOL}-{kind}-{DAY}.zip'
    c=requests.get(BASE+key+'.CHECKSUM',timeout=(15,60));c.raise_for_status();sha=c.text.strip().split()[0]
    r=requests.get(BASE+key,timeout=(15,120));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
    return r.content,sha
def window(body,time_col,hi):
    frames=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',chunksize=150_000):
        z=chunk[(chunk[time_col]>=MINUTE)&(chunk[time_col]<hi)]
        if len(z):frames.append(z)
    return pd.concat(frames,ignore_index=True)
def main():
    cand=pd.read_parquet(PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet')
    e=cand[(cand.symbol==SYMBOL)&(cand.trigger_minute==MINUTE)].iloc[0].to_dict();limit=int(e['quarter_end'])+M
    k,ks=fetch('klines');bars=pd.read_csv(io.BytesIO(k),compression='zip').set_index('open_time')
    a,asum=fetch('aggTrades');agg=window(a,'transact_time',limit).sort_values(['transact_time','agg_trade_id']).reset_index(drop=True)
    raw,rsum=fetch('trades');d=window(raw,'time',limit)
    idcol='id' if 'id' in d.columns else 'trade_id';qtycol='qty' if 'qty' in d.columns else 'quantity'
    d=d.sort_values(['time',idcol]).rename(columns={'time':'transact_time',idcol:'agg_trade_id',qtycol:'quantity'}).reset_index(drop=True)
    one_agg=agg[agg.transact_time<MINUTE+M];one_raw=d[d.transact_time<MINUTE+M];bar=bars.loc[MINUTE]
    def ohlc(g):return [float(g.price.iloc[0]),float(g.price.max()),float(g.price.min()),float(g.price.iloc[-1])]
    official=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
    raw_match=bool(np.allclose(ohlc(one_raw),official,rtol=1e-9,atol=1e-12))
    agg_values=ohlc(one_agg);only_open=bool(not np.isclose(agg_values[0],official[0],rtol=1e-9,atol=1e-12) and
                                           np.allclose(agg_values[1:],official[1:],rtol=1e-9,atol=1e-12))
    def first_cross(g):
        x=g[(g.transact_time<MINUTE+M)&((g.price>e['upper'])|(g.price<e['lower']))].iloc[0]
        return int(x.transact_time),float(x.price)
    ca=first_cross(agg);cr=first_cross(d);cross_match=(ca==cr)
    def reference(g):
        x=g[g.transact_time>=ca[0]+5000].iloc[0];return int(x.transact_time),float(x.price)
    ra=reference(agg);rr=reference(d);reference_match=(ra==rr)
    def flow(g):
        x=g[(g.transact_time>ca[0])&(g.transact_time<ca[0]+5000)]
        maker=x.is_buyer_maker.astype(str).str.lower();amount=x.price.to_numpy(float)*x.quantity.to_numpy(float)
        assert maker.isin(['true','false']).all()
        return [float(amount[maker.eq('false').to_numpy()].sum()),float(amount[maker.eq('true').to_numpy()].sum())]
    fa=flow(agg);fr=flow(d);flow_match=bool(np.allclose(fa,fr,rtol=1e-9,atol=1e-8))
    patched=bars.copy();patched.loc[MINUTE,'open']=agg_values[0]
    outcome=decide(e,agg,patched);paths=[]
    if outcome['status']=='qualified':
        event={**e,**{k:v for k,v in outcome.items() if k not in ('paths','prechecks')}}
        for key,p in outcome['paths'].items():
            lev=int(key.rsplit('_',1)[1].rstrip('x'));fast=key.startswith('fast_');other=simulate_path(event,d,lev,fast)
            fields=['status','entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','reason']
            same=all(k in p and k in other and (np.isclose(p[k],other[k],rtol=1e-11,atol=1e-12) if isinstance(p[k],float) else p[k]==other[k]) for k in fields)
            paths.append({'variant':key,'same':bool(same),'raw_status':other.get('status')})
    valid_status={'qualified','flow_filter_not_met','known_risk_rejected','first_direction_ineligible','no_order_time'}
    pass_all=bool(raw_match and only_open and cross_match and reference_match and flow_match and
                  outcome['status'] in valid_status and (outcome['status']!='qualified' or len(paths)>0) and
                  all(x['same'] for x in paths))
    out={'symbol':SYMBOL,'day':DAY,'minute':MINUTE,'raw_matches_kline_ohlc':raw_match,'aggregate_open_only_differs':only_open,
         'first_cross_aggregate':ca,'first_cross_raw':cr,'cross_match':cross_match,
         'five_second_reference_aggregate':ra,'five_second_reference_raw':rr,'reference_match':reference_match,
         'flow_aggregate_buy_sell':fa,'flow_raw_buy_sell':fr,'flow_match':flow_match,
         'causal_decision_status':outcome['status'],'path_checks':paths,'reconciliation_passed':pass_all,
         'archive_sha256':{'kline':ks,'aggregate':asum,'raw':rsum},
         'note':'A single mismatch only. This compares public market data, not actual fills.'}
    (HERE/'原始成交时序对照个案.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_RAW_RECONCILIATION_SAMPLE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
