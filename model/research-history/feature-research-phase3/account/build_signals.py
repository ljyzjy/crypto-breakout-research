"""Frozen matured-event account opportunities; no future label masks."""
from pathlib import Path
from collections import Counter
import json
import numpy as np
import pandas as pd
from market_io import load_minutes, PHASE2, sha256
from account_market import RankTrendGuard, build_guards

ROOT=Path(__file__).resolve().parent
MINUTE=60_000


def build():
    protocol=json.loads((ROOT.parent/'protocol.json').read_text(encoding='utf-8'))
    lo=int(pd.Timestamp(protocol['splits']['evaluation']['start']).timestamp()*1000)
    hi=int(pd.Timestamp(protocol['splits']['evaluation']['end_exclusive']).timestamp()*1000)
    guards=build_guards()
    guard=RankTrendGuard()
    rankframe=pd.read_parquet(ROOT/'hourly-ranks.parquet')
    ranks={(int(r.hour),r.symbol,int(r.side)):r for r in rankframe.itertuples()}
    result=[];audit=[];counts=Counter()
    for path in sorted((PHASE2/'feature_outputs/events').glob('*.parquet')):
        events=pd.read_parquet(path)
        events=events[events.decision_ts.ge(lo)&events.decision_ts.lt(hi)]
        if not len(events):continue
        contract=events.contract.dropna().iloc[0] if events.contract.notna().any() else None
        raw=load_minutes(contract) if contract else pd.DataFrame()
        times=raw.ts.to_numpy('int64') if len(raw) else np.array([],dtype='int64')
        for r in events.itertuples(index=False):
            why=None;signal=None
            if not bool(r.decision_valid):why='event_not_decision_valid'
            elif not guard.eligible(r.symbol,int(r.side),int(r.decision_ts)):why='decision_rank_or_ema'
            elif int(r.feature_known_ts)>int(r.decision_ts):raise ValueError('Future feature in event')
            else:
                start=np.searchsorted(times,int(r.t0_open_ts))
                stop=np.searchsorted(times,int(r.decision_ts))
                window=raw.iloc[start:stop]
                if len(window)!=6 or not np.array_equal(window.ts.to_numpy(),np.arange(r.t0_open_ts,r.decision_ts,MINUTE)):
                    raise ValueError('Valid event lacks its original six-bar window: '+r.row_id)
                close=float(window.close.iloc[-1]);side=int(r.side);atr=float(r.A)
                if side*(close-float(r.B))<=0:why='decision_not_beyond_boundary'
                else:
                    structural=float(window.low.min())-.1*atr if side==1 else float(window.high.max())+.1*atr
                    distance=side*(close-structural)
                    if distance<=0 or distance>1.5*atr or 2*distance/close<.006:why='decision_stop_or_cost_gate'
                    else:
                        rank=ranks[(int(r.decision_ts)//3_600_000*3_600_000,r.symbol,side)]
                        signal={'ts':int(r.decision_ts)+MINUTE,'decision_ts':int(r.decision_ts),
                            'feature_known_ts':int(r.feature_known_ts),'observation_id':r.row_id,
                            'symbol':r.symbol,'contract':r.contract,'side':side,
                            'signal_close':close,'atr':atr,'stop_price':structural,'level':float(r.B),
                            'break_ts':int(r.t0_open_ts),'touch_ts':int(r.t0_open_ts),
                            'hour':int(rank.hour),'score':float(rank.score),'rank':int(rank.rank),
                            'rvol':float(rank.rvol),'liquidity_rank':int(rank.liquidity_rank),'risk_multiplier':1.}
                        result.append(signal);why='candidate'
            counts[why]+=1
            audit.append({'observation_id':r.row_id,'symbol':r.symbol,'decision_ts':int(r.decision_ts),'reason':why})
    columns=['ts','decision_ts','feature_known_ts','observation_id','symbol','contract','side','signal_close','atr','stop_price','level','break_ts','touch_ts','hour','score','rank','rvol','liquidity_rank','risk_multiplier']
    signals=pd.DataFrame(result,columns=columns).sort_values(['ts','symbol'])
    signals.to_parquet(ROOT/'event-signals.parquet',index=False)
    pd.DataFrame(audit).to_parquet(ROOT/'event-opportunity-audit.parquet',index=False)
    summary={'protocol_sha256':sha256(ROOT.parent/'protocol.json'),'guards':guards,
        'event_rows':len(audit),'signal_rows':len(signals),'reasons':dict(counts),
        'returns_or_future_labels_read':False,
        'input_event_manifest_sha256':sha256(PHASE2/'feature_outputs/manifest.json')}
    (ROOT/'signal_build.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary))


if __name__=='__main__':build()
