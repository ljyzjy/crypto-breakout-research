"""Read-only attribution of frozen backtests; no strategy optimization or trading calls."""
from pathlib import Path
import sys,json,gzip,hashlib
import numpy as np
import pandas as pd

BASE=next(p for p in Path(__file__).resolve().parents if (p/'work/freqtrade-env/Scripts/python.exe').is_file() and (p/'outputs/crypto-spot-kit').is_dir())
ROOT=BASE/'outputs/crypto-spot-kit/short-term-research'
OUT=ROOT/'profitability-diagnosis'
OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT))
import st_engine as eng

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
source_files=[ROOT/n for n in ['st_engine.py','st_factors.py','protocol.json','frozen.json','metrics.json','decision.json','factors.json']]
before={str(p.relative_to(ROOT)):sha(p) for p in source_files}
raw,features=eng.inputs()
metrics=eng.read(ROOT/'metrics.json')
summary=[];details={};all_records=[]

def stats(df):
    wins=df.loc[df.pnl>0,'pnl'];losses=df.loc[df.pnl<0,'pnl']
    total=float(df.pnl.sum());gross=float(df.gross_pnl.sum());fees=float(df.fees.sum());slip=float(df.slippage.sum());n=len(df)
    return {'n':n,'net':total,'gross':gross,'fees':fees,'slippage':slip,'cost':fees+slip,
        'avg_net':total/n if n else None,'avg_gross':gross/n if n else None,
        'win_rate':float((df.pnl>0).mean()*100) if n else None,
        'avg_win':float(wins.mean()) if len(wins) else None,'avg_loss':float(losses.mean()) if len(losses) else None,
        'median_pnl':float(df.pnl.median()) if n else None,
        'profit_factor':float(wins.sum()/-losses.sum()) if len(losses) else None,
        'hold_median':float(df.hold_hours.median()) if n else None,
        'top3_net':float(df.nlargest(3,'pnl').pnl.sum()),
        'without_top3_ledger':float(total-df.nlargest(3,'pnl').pnl.sum()),
        'top3_share_positive_pnl':float(df.nlargest(3,'pnl').pnl.sum()/wins.sum()*100) if len(wins) else None}

def prior_momentum(symbol,ts):
    d=raw[(symbol,'1h')]
    close=d.close.resample('1D',closed='left',label='right').last()
    close=close[d.close.resample('1D',closed='left',label='right').count().eq(24)]
    mom=close/close.shift(30)-1
    return mom.reindex(pd.DatetimeIndex(ts),method='ffill').to_numpy()

for mode in eng.MODES:
    key=f'2025-01-01_2026-10-31_{mode}_10_1h_d0'
    path=ROOT/'results'/f'{key}.json.gz';before[str(path.relative_to(ROOT))]=sha(path)
    r=eng.read(path);df=pd.DataFrame(r['trades'])
    df['entry_time']=pd.to_datetime(df.entry_ts,unit='s',utc=True)
    df['exit_time']=pd.to_datetime(df.exit_ts,unit='s',utc=True)
    df['exit_month']=df.exit_time.dt.strftime('%Y-%m')
    for symbol in eng.SYMBOLS:
        mask=df.symbol.eq(symbol)
        df.loc[mask,'own_mom30']=prior_momentum(symbol,df.loc[mask,'entry_time'])
    df['btc_mom30']=prior_momentum('BTCUSDT',df.entry_time)
    df['own_state']=np.where(df.own_mom30>0,'positive_30d','nonpositive_30d')
    df['market_state']=np.where(df.btc_mom30>0,'BTC_positive_30d','BTC_nonpositive_30d')
    if df[['own_mom30','btc_mom30']].isna().any().any():raise AssertionError('Missing entry regime')
    # Ex-post excursion diagnostic: excludes exit hour/stop hour. It is not a tradable rule.
    rows=[]
    for t in df.itertuples():
        d=raw[(t.symbol,'1h')];f=features[t.symbol]
        src=t.entry_time-pd.Timedelta(hours=1)
        a=f.loc[src,'atr14']
        refclose=raw[(t.symbol,'1h')].loc[src,'close']
        vwap_distance=float((f.loc[src,'vwap24']/refclose-1)*100)
        end=t.exit_time-pd.Timedelta(hours=1) if t.reason=='stop_loss' else t.exit_time
        bars=d.loc[(d.index>=t.entry_time)&(d.index<end)]
        best=max(0.,float(bars.high.max()/t.entry_price-1)*100) if len(bars) else 0.
        worst=min(0.,float(bars.low.min()/t.entry_price-1)*100) if len(bars) else 0.
        rows.append({'mode':mode,**{k:getattr(t,k) for k in ['symbol','entry_ts','exit_ts','reason','pnl','gross_pnl','fees','slippage','hold_hours','own_mom30','btc_mom30','own_state','market_state']},
            'entry_time':str(t.entry_time),'exit_time':str(t.exit_time),
            'completed_hour_mfe_pct':best,'completed_hour_mae_pct':worst,
            'prior_vwap_distance_pct':vwap_distance,
            'fixed_stop_atr_multiple':float(.04*t.entry_price/a) if a>0 else None})
    ex=pd.DataFrame(rows);all_records.extend(rows)
    st=stats(df);st.update({'mode':mode,'name':r['name'],'return_pct':r['return_pct'],'maxdd_pct':r['max_drawdown'],
        'avg_exposure_pct':r['mean_exposure_pct'],'mean_hold_hours':r['mean_hold_hours'],
        'roundtrip_gross_bp':st['avg_gross'],'roundtrip_cost_bp':st['cost']/st['n'],
        'required_cost_reduction_pct':(1-st['gross']/st['cost'])*100,
        'fixed_path_net_fee_zero':st['net']+st['fees'],
        'guard_activations':r['guard_activations'],'blocked_signals':r['blocked_entry_signals']})
    # 1 USDT on 100 stake = 100 bp; explicitly convert the per-trade amounts.
    st['roundtrip_gross_bp']*=100;st['roundtrip_cost_bp']*=100
    nominal=sum(t['qty']*(t['entry_price']+t['exit_price']) for t in r['trades'])
    st['breakeven_fee_per_side_pct_fixed_path']=(st['gross']-st['slippage'])/nominal*100
    st['breakeven_win_rate_fixed_payoffs_pct']=abs(st['avg_loss'])/(st['avg_win']+abs(st['avg_loss']))*100
    st['stop_atr_quantiles']=ex.fixed_stop_atr_multiple.quantile([.1,.5,.9]).to_dict()
    st['prior_vwap_distance_pct_quantiles']=ex.prior_vwap_distance_pct.quantile([.1,.5,.9]).to_dict()
    roundtrip_threshold=((1+.0005)*(1+.001)/((1-.0005)*(1-.001))-1)*100
    st['entry_vwap_target_below_roundtrip_cost_count']=int((ex.prior_vwap_distance_pct<roundtrip_threshold).sum())
    st['entry_vwap_target_below_roundtrip_cost_fraction']=float((ex.prior_vwap_distance_pct<roundtrip_threshold).mean())
    st['negative_trades_with_prior_mfe_ge_0_3pct']=int(((ex.pnl<0)&(ex.completed_hour_mfe_pct>=.3)).sum())
    st['negative_trades']=int((ex.pnl<0).sum())
    summary.append(st)
    by={k:{str(g):stats(z) for g,z in df.groupby(k)} for k in ['symbol','reason','own_state','market_state','exit_month']}
    by['top_trades']=df.nlargest(5,'pnl')[['symbol','entry_time','exit_time','pnl','hold_hours','reason']].astype({'entry_time':str,'exit_time':str}).to_dict('records')
    by['worst_trades']=df.nsmallest(3,'pnl')[['symbol','entry_time','exit_time','pnl','hold_hours','reason']].astype({'entry_time':str,'exit_time':str}).to_dict('records')
    details[mode]=by
    assert abs(st['net']-(r['final_equity']-1000))<1e-7
    assert abs(st['gross']-st['fees']-st['slippage']-st['net'])<1e-7
    assert abs(sum(x['net'] for x in by['reason'].values())-st['net'])<1e-7
    assert abs(sum(x['net'] for x in by['own_state'].values())-st['net'])<1e-7

annual=[]
annual_regimes=[]
for r in metrics:
    if r['resolution']=='1h' and r['fee']==.001 and r['window'] in ['2023','2024','2025','2026','early','later']:
        annual.append({k:r[k] for k in ['mode','window','return_pct','max_drawdown','trade_count','mean_exposure_pct','contributions','valid_for_comparison']})
        if r['window'] in ['2023','2024','2025','2026']:
            rp=ROOT/'results'/f"{r['id']}.json.gz"
            before[str(rp.relative_to(ROOT))]=sha(rp)
            ad=pd.DataFrame(eng.read(rp)['trades'])
            assert abs(float(ad.pnl.sum())-(r['final_equity']-1000))<1e-7
            ad['entry_time']=pd.to_datetime(ad.entry_ts,unit='s',utc=True)
            for sym in eng.SYMBOLS:
                mask=ad.symbol.eq(sym)
                ad.loc[mask,'own_mom30']=prior_momentum(sym,ad.loc[mask,'entry_time'])
            ad['own_state']=np.where(ad.own_mom30>0,'positive_30d','nonpositive_30d')
            assert ad.own_mom30.notna().all()
            for group,part in ad.groupby('own_state'):
                annual_regimes.append({'mode':r['mode'],'window':r['window'],'state':group,'valid_for_comparison':r['valid_for_comparison'],**stats(part)})

# Passive comparator with the same initial cash, entry notional, fees and slippage.
# It has no stop, cooldown or exit timing, hence a different exposure path and risk.
passive={};slip=.0005;fee=.001
for label,start,end in [('later','2025-01-01','2026-10-31'),('2025','2025-01-01','2025-12-31'),('2026','2026-01-01','2026-10-31')]:
    b=pd.Timestamp(start,tz='UTC');e=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    curve=None;items={}
    for sym in eng.SYMBOLS:
        d=raw[(sym,'1h')].loc[lambda x:(x.index>=b)&(x.index<e)]
        qty=100/(float(d.open.iloc[0])*(1+slip));proceeds=qty*float(d.close.iloc[-1])*(1-slip)*(1-fee)
        net=proceeds-100*(1+fee)
        items[sym]={'net':net,'asset_price_return_pct':float((d.close.iloc[-1]/d.open.iloc[0]-1)*100)}
        position=qty*d.close
        curve=position if curve is None else curve+position
    curve=curve+1000-200*(1+fee);curve.iloc[-1]=1000+sum(x['net'] for x in items.values())
    curve=pd.concat([pd.Series([1000.],index=[b-pd.Timedelta(seconds=1)]),curve])
    passive[label]={'return_pct':float((curve.iloc[-1]/1000-1)*100),'maxdd_pct':float(((1-curve/curve.cummax())*100).max()),'contributions':items,
        'note':'100 USDT BTC + 100 USDT ETH at start, 799.80 cash; liquidation at end, both-side fees/slippage. No stop; differs in exposure.'}

after={name:sha(ROOT/name) for name in before}
assert before==after
for t in all_records:
    # The attribution adds existing accounting components; never deduct costs twice.
    assert abs(t['gross_pnl']-t['fees']-t['slippage']-t['pnl'])<1e-8
report={'scope':'Frozen 2025-01-01 through 2026-10-31, 1h base fee, USDT; independent calendar comparisons reset cash.',
 'source_hashes':before,'checks':{'inputs_unchanged':True,'net_account_reconciliation':True,'cost_identity':True,'exclusive_bucket_reconciliation':True},
 'summary':summary,'details':details,'annual_independent_runs':annual,'annual_entry_regimes':annual_regimes,'passive_comparator':passive,
 'limits':['Post-hoc diagnostic, no causal attribution of filters or exits. No new strategy has been backtested.',
 'Top-three removal is ledger sensitivity, not re-execution. Entry-regime buckets do not include portfolio interactions.',
 'Regimes use only fully closed daily bars available at entry. All examined history is now seen.',
 'MFE/MAE use only completed pre-exit hours; these extrema are not executable profits.',
 'Monthly grouping is realized PnL by exit month, not mark-to-market monthly return.',
 'Fee break-even holds filled path fixed and assumes common proportional fees; not an exchange quote.']}
(OUT/'attribution.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
(OUT/'trade-diagnostics.json').write_text(json.dumps(all_records,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print('SUMMARY')
print(pd.DataFrame(summary)[['mode','n','net','gross','cost','avg_net','avg_gross','win_rate','avg_win','avg_loss','without_top3_ledger','mean_hold_hours','avg_exposure_pct','breakeven_fee_per_side_pct_fixed_path']].round(4).to_string(index=False))
print('PASSIVE',json.dumps(passive,ensure_ascii=False))
for mode,ds in details.items():
    print('ATTRIBUTION',mode,json.dumps({k:{g:{q:x[q] for q in ['n','net','avg_net','win_rate']} for g,x in ds[k].items()} for k in ['reason','own_state','market_state']},ensure_ascii=False))
print('ANNUAL_REGIMES')
print(pd.DataFrame(annual_regimes)[['mode','window','state','n','net','avg_net']].round(4).to_string(index=False))
print('MOMENTUM_TOP',json.dumps(details['DailyMomentum']['top_trades'],ensure_ascii=False))
print('ATR_AND_MFE',json.dumps([{k:s[k] for k in ['mode','stop_atr_quantiles','negative_trades','negative_trades_with_prior_mfe_ge_0_3pct']} for s in summary],ensure_ascii=False))
print('INPUTS_UNCHANGED_AND_RECONCILED')
