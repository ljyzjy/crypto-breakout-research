"""Build only causal signals/features. No forward outcomes calculated."""
from common import *
from collections import Counter

def candidate(seed,times,a,guard,ranks,variant,asof=END):
    side=int(seed.side);A=float(seed.A);B=float(seed.B);t0=int(seed.t0_open_ts)
    if not np.isfinite(A) or A<=0:return None,'initial_atr'
    touch=t0
    if variant=='B':
        t=int(seed.decision_ts)
        if t>asof or not bool(seed.decision_valid):return None,'B_decision_invalid'
    else:
        touch=None;t=None
        for k in range(1,16):
            baropen=t0+k*M;known=baropen+M
            if known>asof or known>=END:return None,'C_pending_deadline'
            w=span(times,a,baropen,known)
            if w is None or not valid_bars(w).all():return None,'C_missing'
            bar=w[0]
            if side*(bar[3]-B)<-.25*A:return None,'C_failed_boundary'
            if touch is not None:
                prev=span(times,a,baropen-M,baropen)
                confirm=side*(bar[3]-B)>0 and (bar[3]>prev[0,1] if side==1 else bar[3]<prev[0,2])
                if confirm:t=known;break
            if touch is None and bar[2]<=B+.25*A and bar[1]>=B-.25*A:touch=baropen
        if t is None:return None,'C_no_later_confirmation'
    if not LO<=t<END or t>asof:return None,'outside_study'
    if t>=load_quarantine().get(seed.symbol,{}).get('known_ts',10**18):return None,'known_quarantine'
    if not guard.eligible(seed.symbol,side,t):return None,'decision_rank_or_ema'
    w=span(times,a,t0,t)
    if w is None or not valid_bars(w).all():return None,'invalid_window'
    close=float(w[-1,3])
    if side*(close-B)<=0:return None,'not_outside'
    stop=float(w[:,2].min()-.1*A if side==1 else w[:,1].max()+.1*A);distance=side*(close-stop)
    if distance<=0 or distance>1.5*A or 2*distance/close<.006:return None,'decision_stop_cost'
    rank=ranks[(t//H*H,seed.symbol,side)]
    s={'ts':t+M,'decision_ts':t,'feature_known_ts':t,'observation_id':str(seed.row_id) if variant=='B' else 'C|'+str(seed.row_id),
      'base_event_id':str(seed.row_id),'variant':variant,'symbol':seed.symbol,'contract':seed.contract,'side':side,
      'signal_close':close,'atr':A,'stop_price':stop,'level':B,'break_ts':t0,'touch_ts':int(touch),
      'hour':int(rank.hour),'score':float(rank.score),'rank':int(rank.rank),'rvol':float(rank.rvol),'liquidity_rank':int(rank.liquidity_rank),'risk_multiplier':1.}
    return s,'candidate'

def main():
    guard=RankTrendGuard();ranks={(int(r.hour),r.symbol,int(r.side)):r for r in pd.read_parquet(P3/'account/hourly-ranks.parquet').itertuples()}
    pio=phase2_io();btc=hourly('BTCUSDT','BTCUSDT');out=[];reasons=Counter();audit=[];causal=[]
    for path in sorted((P2/'feature_outputs/events').glob('*.parquet')):
        events=pd.read_parquet(path)
        if events.contract.notna().sum()==0:continue
        symbol=str(events.symbol.iloc[0]);contract=str(events.contract.dropna().iloc[0])
        raw=pio.load_minutes(contract);times=raw.ts.to_numpy('int64');a=raw[['open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume']].to_numpy(float)
        h=hourly(symbol,contract);local=[]
        for seed in events.itertuples(index=False):
            for variant in ['B','C']:
                s,why=candidate(seed,times,a,guard,ranks,variant)
                reasons[variant+':'+why]+=1
                if s is not None:
                    f=feature_vector(s,times,a,h,btc);s['features_valid']=f is not None
                    s.update(f if f is not None else {k:np.nan for k in FEATURES});local.append((s,seed))
                audit.append({'base_event_id':seed.row_id,'variant':variant,'reason':why})
        # Deterministic first/middle/last prefix checks for both versions, every symbol.
        for variant in ['B','C']:
            valid=[x for x in local if x[0]['variant']==variant and x[0]['features_valid']]
            for j in sorted(set([0,len(valid)//2,len(valid)-1])) if valid else []:
                s,seed=valid[j];t=s['decision_ts'];end=np.searchsorted(times,t)
                shorter,why=candidate(seed,times[:end],a[:end],guard,ranks,variant,asof=t)
                assert shorter is not None,(symbol,variant,why)
                assert all(shorter[k]==s[k] for k in shorter)
                fp=feature_vector(shorter,times[:end],a[:end],h.loc[h.index<=t],btc.loc[btc.index<=t])
                assert all(np.isclose(fp[k],s[k],equal_nan=True,rtol=0,atol=1e-12) for k in FEATURES)
                causal.append({'id':s['observation_id'],'variant':variant,'decision_ts':t,'prefix_invariant':True})
        out.extend(s for s,seed in local)
        print('BUILD',symbol,'signals',len(local),flush=True)
    d=pd.DataFrame(out).sort_values(['variant','ts','symbol']).reset_index(drop=True)
    assert d.observation_id.is_unique
    b=d[(d.variant=='B')&d.decision_ts.ge(CAL_END)].copy()
    old=pd.read_parquet(P3/'account/event-signals.parquet')
    cols=old.columns.tolist()
    pd.testing.assert_frame_equal(b[cols].sort_values('observation_id').reset_index(drop=True),old[cols].sort_values('observation_id').reset_index(drop=True),check_dtype=False,check_exact=True)
    c=d[d.variant=='C'];assert (c.touch_ts+M<c.decision_ts).all();assert (c.decision_ts<=c.break_ts+16*M).all()
    save('signals/all.parquet',d);save('signals/opportunity_audit.parquet',pd.DataFrame(audit))
    summary={'reasons':dict(reasons),'counts':d.groupby(['variant','features_valid']).size().to_dict(),'baseline_evaluation_exact_match':len(b),'prefix_checks':causal,'outcomes_read':False}
    summary['counts']={str(k):int(v) for k,v in summary['counts'].items()}
    dump(OUT/'signals/build_audit.json',summary)
    dump(OUT/'signals/READY.json',{'all_sha256':sha(OUT/'signals/all.parquet'),'protocol_sha256':sha(OUT/'protocol.json')})
    print('SIGNALS_READY',summary['counts'],flush=True)

if __name__=='__main__':main()
