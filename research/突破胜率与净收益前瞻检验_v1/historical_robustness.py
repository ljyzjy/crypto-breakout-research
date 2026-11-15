"""Apply the same frozen variants to previously inspected dynamic-pool history."""
import importlib.util,json,sys
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
GE=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P3=GE/'outputs'/'feature-research-phase3'/'account'
PREV=HERE.parent/'突破柱融合研究_v1'
sys.path.insert(0,str(P3))
from account_market import Market,RankTrendGuard
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
prior=load('historical_prior',PREV/'research.py')
forward=load('historical_forward_helpers',HERE/'forward_research.py')
eng=load('historical_target_engine',HERE/'engine_target_copy.py')
M=60_000;Q=15*M
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
      default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

def confirmed_from_first(first,guard):
    mapping=prior.pio.load_mapping();refs={};counts=Counter();out=[]
    for symbol in ['BTCUSDT','ETHUSDT']:
        a,ok=prior.load_dense(mapping[symbol]);refs[symbol]={'close':a[:,3],'valid':ok,**prior.calculate(a,ok)}
    ranks=pd.read_parquet(P3/'hourly-ranks.parquet')
    ranks={(int(r.hour),r.symbol,int(r.side)):r for r in ranks.itertuples()}
    for contract,g in first.groupby('contract'):
        raw=prior.pio.load_minutes(contract,int(g.break_ts.min()),int(g.break_ts.max())+2*M).set_index('ts')
        if not raw.index.is_unique:raise ValueError('Duplicate minute')
        for s in g.itertuples(index=False):
            t0=int(s.break_ts);d2=int(s.decision_ts)+M;e2=d2+M;quarter_end=(t0//Q+1)*Q
            if e2>=quarter_end:counts['too_late']+=1;continue
            if t0 not in raw.index or t0+M not in raw.index:counts['missing']+=1;continue
            a=raw.loc[[t0,t0+M]][['open','high','low','close','volume','quote_volume']].to_numpy(float)
            o,h,l,c,v,q=a.T
            valid=np.isfinite(a).all() and (a>0).all() and (h>=np.maximum.reduce([o,l,c])).all() and (l<=np.minimum.reduce([o,h,c])).all()
            if not valid:counts['invalid']+=1;continue
            j=np.searchsorted(prior.GRID,t0+M)
            if j>=len(prior.GRID) or prior.GRID[j]!=t0+M:raise ValueError('Reference grid mismatch')
            side=int(s.side)
            if not guard.eligible(s.symbol,side,d2) or not forward.ref_state(refs,j,side):counts['guard']+=1;continue
            close=float(c[-1]);atr=float(s.atr);level=float(s.level)
            if side*(close-level)<=0:counts['back_inside']+=1;continue
            stop=float(l.min()-.1*atr if side==1 else h.max()+.1*atr);dist=side*(close-stop)
            if dist<=0 or dist>1.5*atr or 2*dist/close<.006:counts['stop_cost']+=1;continue
            rank=ranks[(d2//3_600_000*3_600_000,s.symbol,side)]
            out.append({'ts':e2,'decision_ts':d2,'feature_known_ts':d2,
               'observation_id':'confirm|'+s.observation_id,'symbol':s.symbol,'contract':contract,'side':side,
               'signal_close':close,'atr':atr,'stop_price':stop,'level':level,'break_ts':t0,'touch_ts':t0,
               'quarter_start':t0//Q*Q,'hour':int(rank.hour),'score':float(rank.score),'rank':int(rank.rank),
               'rvol':float(rank.rvol),'liquidity_rank':int(rank.liquidity_rank),'risk_multiplier':1.})
    cols=['ts','decision_ts','feature_known_ts','observation_id','symbol','contract','side','signal_close','atr','stop_price','level','break_ts','touch_ts','quarter_start','hour','score','rank','rvol','liquidity_rank','risk_multiplier']
    result=pd.DataFrame(out,columns=cols).sort_values(['ts','symbol']).reset_index(drop=True)
    assert (result.ts<result.quarter_start+Q).all() and (result.feature_known_ts<=result.decision_ts).all()
    result.to_parquet(HERE/'历史确认信号.parquet',index=False)
    dump(HERE/'历史确认信号核对.json',{'first_candidates':len(first),'confirmed_candidates':len(result),'rejections':dict(counts)})
    return result

def main():
    first=pd.read_parquet(PREV/'signals.parquet');first=first[first.sync_pass].copy()
    guard=RankTrendGuard();confirm=confirmed_from_first(first,guard)
    variants=[('baseline_2r',first,2.),('target_1r',first,1.),('target_1_5r',first,1.5),('confirm_1r',confirm,1.)]
    scenarios=[('main',.0005,.0005,0),('double',.001,.001,0),('delay1',.0005,.0005,1)]
    results=[]
    for name,sig,target in variants:
      for tag,fee,slip,delay in scenarios:
        scenario={'id':tag,'fee':fee,'slippage':slip,'delay_minutes':delay,'target_r':target}
        sm,curve,trades,entries,funding=eng.simulate(scenario,sig,'2025-07-01','2026-04-26',
           market=Market(),guard=guard,save=False,run_id=name)
        sm['period']='historical_dynamic_pool';sm['target_r']=target
        sm['net_win_rate_pct']=sm['win_rate'] if trades else None
        if sm['valid_for_comparison']:
            assert abs(sm['final_equity']-1000-sum(t['net'] for t in trades))<1e-6
        if name=='baseline_2r' and tag=='main':
            old=json.loads((PREV/'early_sync_main_summary.json').read_text(encoding='utf-8'))
            assert sm['trades']==old['trades'] and abs(sm['net_pnl']-old['net_pnl'])<1e-8
        stem=f'historical_{name}_{tag}'
        dump(HERE/f'{stem}_summary.json',sm);dump(HERE/f'{stem}_trades.json',trades)
        curve.to_parquet(WORK/f'{stem}_curve.parquet',index=False)
        results.append(sm)
        print('HIST_ACCOUNT',stem,json.dumps({k:sm.get(k) for k in ['trades','net_win_rate_pct','net_pnl','max_drawdown','valid_for_comparison','issues']}),flush=True)
    dump(HERE/'历史稳健性全部结果.json',results)
    cols=['run_id','scenario','signal_candidates','trades','net_win_rate_pct','net_pnl','return_pct','max_drawdown','profit_factor','valid_for_comparison','issues']
    pd.DataFrame(results).reindex(columns=cols).to_csv(HERE/'历史动态币池对照.csv',index=False,encoding='utf-8-sig')
    print('HISTORICAL_COMPLETE',flush=True)
if __name__=='__main__':main()
