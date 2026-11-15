"""Fixed experiment manifest, execution, ledger metrics and causal validation."""
import collections,gzip,hashlib,json,time
from pathlib import Path
import numpy as np
import pandas as pd
import engine

ROOT=Path(__file__).resolve().parent
P=json.loads((ROOT/'protocol.json').read_text())
LABELS={'baseline':'BTC/ETH 动量对照','selection':'V1 原选币组合','liquidity4':'流动性四币等权',
        'relative4':'四币相对动量','core_satellite':'BTC/ETH 核心＋单卫星',
        'no_market_gate':'仅去掉 BTC 大盘过滤','no_ma100':'仅去掉个币 MA100',
        'daily_vacancy_entry':'仅允许每日补空缺','equal_weights':'仅改为等权','no_rebalance':'仅关闭持仓再平衡'}

def fingerprint():
    paths=[ROOT/'protocol.json',ROOT/'engine.py',ROOT/'study.py',ROOT/'test_study.py',
           engine.SOURCE/'universe.json',engine.SOURCE/'rules.json']+sorted((engine.SOURCE/'data').glob('*.feather'))
    return {str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def metric(r):
    fees=sum(o['fee'] for o in r['orders'])
    slip=sum(o['qty']*abs(o['price']-o['price']/(1+r['slippage'] if o['side']=='buy' else 1-r['slippage'])) for o in r['orders'])
    sells=[o for o in r['orders'] if o['side']=='sell'];pairs=collections.defaultdict(float);reasons={}
    for o in sells:
        pairs[o['symbol']]+=o['pnl'];item=reasons.setdefault(o['reason'],{'fills':0,'pnl':0.})
        item['fills']+=1;item['pnl']+=o['pnl']
    eq=pd.Series([e['equity'] for e in r['equity']],index=pd.to_datetime([e['date'] for e in r['equity']]))
    ret=eq.pct_change();ret.iloc[0]=eq.iloc[0]/1000-1
    row={k:r[k] for k in ['mode','extra_lag','start','end','fee','slippage','return_pct','max_drawdown','exit_fills','order_count','mean_exposure','valid_for_comparison']}
    row.update(fees=fees,slippage_cost=slip,fixed_fill_gross_pnl=r['return_pct']*10+fees+slip,
               turnover=sum(o['qty']*o['price'] for o in r['orders'])/eq.mean(),
               cash_days=sum(e['exposure']==0 for e in r['equity']),days=len(eq),
               gate_off_days=sum(not t['risk_on'] for t in r['trace']),
               fee_per_exposure=fees/max(1e-9,r['mean_exposure']*1000),
               daily_sharpe=float(ret.mean()/ret.std()*np.sqrt(365)) if ret.std()>0 else None,
               worst_month_pct=float(((1+ret).resample('ME').prod()-1).min()*100),
               pair_pnl=dict(pairs),exit_reasons=reasons,missing_price_events=len(r['missing_held_prices']),
               top3_positive_fill_share=sum(sorted([o['pnl'] for o in sells if o['pnl']>0],reverse=True)[:3])/max(1e-9,sum(o['pnl'] for o in sells if o['pnl']>0)))
    if r['valid_for_comparison']:
        assert abs(sum(pairs.values())-r['return_pct']*10)<1e-6
        cash=1000
        for o in r['orders']:cash+=o['qty']*o['price']-o['fee'] if o['side']=='sell' else -o['qty']*o['price']-o['fee']
        assert abs(cash-r['equity'][-1]['equity'])<1e-6
    assert min(e['cash'] for e in r['equity'])>=-1e-7
    return row

def reconciliation(data):
    results=[]
    for window in ['early','later']:
        start,end=P['windows'][window]
        for mode in ['baseline','selection']:
            r=engine.simulate(data,start,end,.001,mode)
            old=json.loads((engine.SOURCE/'results'/f'{mode}-{start}-{end}-0.001.json').read_text())
            for k in ['return_pct','max_drawdown','mean_exposure']:assert abs(r[k]-old[k])<1e-10,(mode,k)
            assert r['orders']==old['orders']
            assert r['trace']==old['trace']
            metric(r);results.append({'mode':mode,'window':window,'exact_orders_and_decisions':'PASS'})
    return results

def run():
    data=engine.load();recon=reconciliation(data)
    print('V1 exact replay PASS',flush=True)
    fp=fingerprint();frozen=ROOT/'frozen.json'
    if frozen.exists():assert json.loads(frozen.read_text())['hashes']==fp,'Frozen study changed'
    else:frozen.write_text(json.dumps({'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'hashes':fp},indent=2))
    (ROOT/'reconciliation.json').write_text(json.dumps(recon,indent=2))
    jobs=[]
    for w in ['early','later']:
        for mode in P['main_variants']:
            for fee in [.001,.002,.003]:jobs.append((w,mode,fee,0))
            jobs.append((w,mode,.001,1))
        for mode in P['diagnostic_variants']:jobs.append((w,mode,.001,0))
    for w in ['2023','2024','2025','2026']:
        for mode in P['main_variants']:jobs.append((w,mode,.001,0))
    assert len(jobs)==70
    folder=ROOT/'results';folder.mkdir(exist_ok=True)
    rows=[]
    for i,(w,mode,fee,lag) in enumerate(jobs,1):
        key=f'{w}-{mode}-{fee:.3f}-lag{lag}';cache=folder/(key+'.json.gz')
        if cache.exists():
            with gzip.open(cache,'rt',encoding='utf-8') as f:r=json.load(f)
        else:
            r=engine.simulate(data,*P['windows'][w],fee,mode,extra_lag=lag)
            with gzip.open(cache,'wt',encoding='utf-8') as f:json.dump(r,f,ensure_ascii=False,allow_nan=False)
        row=metric(r);row.update(window=w,key=key,label=LABELS[mode]);rows.append(row)
        print(f'{i}/70 {key}: return={row["return_pct"]:.4f}% DD={row["max_drawdown"]:.4f}% valid={row["valid_for_comparison"]}',flush=True)
    (ROOT/'metrics.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    pd.DataFrame([{k:v for k,v in r.items() if k not in ('pair_pnl','exit_reasons')} for r in rows]).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
    assert fingerprint()==fp
    print('70 runs finished; frozen inputs unchanged',flush=True)

if __name__=='__main__':run()
