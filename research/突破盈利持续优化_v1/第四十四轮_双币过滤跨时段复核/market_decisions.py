"""BTC/ETH previous-closed-quarter activity; never read current quarter data."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;Q=900_000
def classify(q,lookup,suspect):
    outcomes=[];extra={}
    for symbol in ('BTCUSDT','ETHUSDT'):
        hist=[]
        for t in range(int(q)-21*Q,int(q),Q):
            b=lookup.get((symbol,t))
            if b is None or (symbol,t) in suspect:hist=[];break
            if b['volume']<=0 or b['count']<=0 or b['open']<=0 or b['close']<=0:hist=[];break
            hist.append(b)
        tag=symbol[:3].lower()
        if len(hist)!=21:
            outcomes.append(('unknown',0));extra[tag+'_n']=None;extra[tag+'_p']=None;continue
        p=sum(int(x['count']) for x in hist[:20]);n=int(hist[20]['count']);b=hist[20]
        side=1 if b['close']>b['open'] else -1 if b['close']<b['open'] else 0
        extra[tag+'_n']=n;extra[tag+'_p']=p
        if p<=0:outcomes.append(('unknown',0))
        elif 40*n<3*p or side==0:outcomes.append(('rejected',0))
        else:outcomes.append(('passed',side))
    if any(x[0]=='rejected' for x in outcomes):return {'market_status':'known_no_order','allowed_side':0,**extra}
    if any(x[0]=='unknown' for x in outcomes):return {'market_status':'market_unknown','allowed_side':0,**extra}
    if outcomes[0][1]!=outcomes[1][1]:return {'market_status':'known_no_order','allowed_side':0,**extra}
    return {'market_status':'allowed','allowed_side':outcomes[0][1],**extra}
def main():
    frozen=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==frozen['plan_sha256']
    signal=H/'冻结输入'/'baseline_signal.parquet';assert hashlib.sha256(signal.read_bytes()).hexdigest()==frozen['inputs']['baseline_signal.parquet']
    s=pd.read_parquet(signal);bars=pd.read_parquet(H/'BTC_ETH过去十五分钟数据.parquet');assert not bars.duplicated(['symbol','open_time']).any()
    lookup={(r['symbol'],int(r['open_time'])):r for r in bars.to_dict('records')}
    audit=json.loads((H/'BTC_ETH一分钟样本核验.json').read_text(encoding='utf-8'))
    suspect={(x['symbol'],int(x['open_time'])) for x in audit['samples'] if x['status']!='verified'}
    qvalues=sorted(set(map(int,s.quarter_start)));byq={q:classify(q,lookup,suspect) for q in qvalues}
    rows=[{'observation_id':r.observation_id,'quarter_start':int(r.quarter_start),**byq[int(r.quarter_start)]} for r in s.itertuples(index=False)]
    d=pd.DataFrame(rows);assert d.observation_id.is_unique and len(d)==len(s)
    d.to_parquet(H/'候选事前市场过滤.parquet',index=False)
    result={'candidate_events':len(d),'unique_quarters':len(qvalues),'market_status_counts':d.market_status.value_counts().to_dict(),
            'source_sha256':hashlib.sha256((H/'BTC_ETH过去十五分钟数据.parquet').read_bytes()).hexdigest(),
            'plan_sha256':frozen['plan_sha256'],'decision_sha256':hashlib.sha256((H/'候选事前市场过滤.parquet').read_bytes()).hexdigest(),
            'note':'Only previous 21 completed 15-minute bars per symbol; no training outcomes used.'}
    (H/'事前市场过滤质量.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL42_DECISIONS',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
