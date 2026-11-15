"""Independent cash/equity and source reconciliation of all fixed cost cases."""
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent; ACC=ROOT.parent/'account'; INC=ROOT.parent/'incremental'
sys.path.insert(0,str(ACC))
import market_io
M=60_000; DAY=86_400_000
LO=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp()*1000)
HI=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)
N=(HI-LO)//M
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b,atol=1e-8):np.testing.assert_allclose(a,b,rtol=1e-10,atol=atol)
MARK_CACHE={}; PRICE_CACHE={}; FUND_CACHE={}
def market(c,start,end):
    key=(c,start//(30*DAY),end//(30*DAY))
    # Per trade windows; all market files are independently checked by frozen loader.
    d=market_io.load_minutes(c,start,end).set_index('ts')
    mark=market_io.load_mark(c,start,end).set_index('ts')
    return d,mark

def main():
    ready=read(ACC/'ACCOUNT_RESULTS_READY.json')
    assert ready['summary_sha256']==sha(ACC/'account_results.json')
    freeze=read(ACC/'execution_freeze.json')
    for name,h in freeze['files'].items():assert sha(ACC/name)==h,(name,'frozen source drift')
    assert read(INC/'selection.json')['selected_groups']==[]
    report=read(ACC/'account_results.json'); results=[]; checked_trades=0; checked_fund=0
    ranks=pd.read_parquet(ACC/'hourly-ranks.parquet')
    rank_keys=set(zip(ranks.hour.astype(int),ranks.symbol,ranks.side.astype(int)))
    regimes=pd.read_parquet(ACC/'regimes.parquet')
    qr={s:g.sort_values('ts').set_index('ts').direction for s,g in regimes.groupby('symbol')}
    signals=pd.read_parquet(ACC/'event-signals.parquet').set_index('observation_id')
    for summary in report['results']:
        case=summary['scenario']; base=ACC/'results/event_baseline'
        curve=pd.read_parquet(base/f'{case}-curve.parquet')
        trades=read(base/f'{case}-trades.json'); entries=read(base/f'{case}-entries.json'); funding=read(base/f'{case}-funding.json')
        assert summary['valid_for_comparison'] and not summary['issues']
        assert len(curve)==N and np.array_equal(curve.ts,LO+np.arange(1,N+1)*M)
        assert len(trades)==len(entries)==summary['trades']
        changes=np.zeros(N+1); stress_cash=np.zeros(N+1); unreal=np.zeros(N); adverse=np.zeros(N)
        expected_positions=np.zeros(N,dtype=int); active=np.zeros(N,dtype=bool)
        entry_lookup={(e['symbol'],e['ts']):e for e in entries}
        trade_lookup={(t['symbol'],t['entry_ts']):t for t in trades}
        for t in trades:
            e=entry_lookup[(t['symbol'],t['entry_ts'])]; s=1 if t['side']=='long' else -1
            q=t['qty']; te=int(t['entry_ts']); tx=int(t['exit_ts']); i=(te-LO)//M
            j=(tx-LO)//M
            intrabar=t['reason'] in ['stop','target','period_end']
            exit_record=j-1 if intrabar else j
            sig=signals.loc[t['observation_id']]
            assert t['decision_ts']==int(sig.decision_ts)
            assert te==int(sig.ts)+summary['delay_minutes']*M
            assert e['feature_known_ts']<=e['decision_ts']<te
            assert (te//3_600_000*3_600_000,t['symbol'],s) in rank_keys
            r=qr[t['symbol']]; at=r.index.searchsorted(te,side='right')-1
            assert at>=0 and te-int(r.index[at])<900_000 and int(r.iloc[at])==s
            near(t['entry'],t['raw_entry']*(1+s*summary['slippage']))
            near(t['exit'],t['raw_exit']*(1-s*summary['slippage']))
            near(t['entry_fee'],q*t['entry']*summary['fee']);near(t['exit_fee'],q*t['exit']*summary['fee'])
            near(t['gross'],s*q*(t['raw_exit']-t['raw_entry']))
            near(t['slippage'],q*(abs(t['entry']-t['raw_entry'])+abs(t['exit']-t['raw_exit'])))
            near(t['net'],s*q*(t['exit']-t['entry'])-t['entry_fee']-t['exit_fee']-t['funding'])
            near(t['target'],t['entry']+s*2*s*(t['entry']-t['stop']))
            assert e['notional']<=.5*e['known_equity']+1e-8 and e['gross_after']<=e['known_equity']+1e-8
            assert e['notional']<=.001*e['previous_quote_volume']+1e-8 and e['slots']<=2
            assert e['aggregate_planned_loss']<=e['portfolio_risk_cap']*e['known_equity']+1e-8
            assert e['risk_fraction']<=.0025 and t['risk_multiplier']==1
            assert te-t['decision_ts']>=M and tx-te<=60*M
            px,mp=market(t['contract'],te-M,tx+M)
            expected_funding=market_io.load_funding(t['contract'],te,tx+(0 if intrabar else M))
            recorded_funding=[f for f in funding if f['symbol']==t['symbol'] and f['entry_ts']==te]
            assert sorted(expected_funding.ts.astype(int))==sorted(int(f['settlement_ts']) for f in recorded_funding)
            near(float(px.loc[te,'open']),t['raw_entry'])
            if t['reason']=='stop':near(t['raw_exit'],t['stop'])
            elif t['reason']=='target':near(t['raw_exit'],t['target'])
            elif t['reason']=='period_end':near(t['raw_exit'],px.loc[tx-M,'close'])
            else:near(t['raw_exit'],px.loc[tx,'open'])
            # Independently enforce first-hit/gap handling in each held interval.
            for ts in range(te,tx,M):
                bar=px.loc[ts]
                sh=(bar.low<=t['stop']) if s==1 else (bar.high>=t['stop'])
                th=(bar.high>=t['target']) if s==1 else (bar.low<=t['target'])
                if sh or th:
                    assert intrabar and tx==ts+M
                    assert t['reason']==('stop' if sh else 'target')
                    assert t['ambiguous']==bool(sh and th)
            if t['reason']=='gap_stop':assert s*(px.loc[tx,'open']-t['stop'])<=0
            if t['reason']=='gap_target':assert s*(px.loc[tx,'open']-t['target'])>=0
            # Curve cash changes are applied when the minute record observes them.
            changes[i]-=t['entry_fee']; changes[exit_record]+=s*q*(t['exit']-t['entry'])-t['exit_fee']
            stress_cash[i]-=t['entry_fee']; stress_cash[j]+=s*q*(t['exit']-t['entry'])-t['exit_fee']
            for k in range(i,exit_record):
                bar_ts=LO+k*M
                unreal[k]+=s*q*(float(mp.loc[bar_ts,'close'])-t['entry']);expected_positions[k]+=1
            for k in range(i,j):
                mark=mp.loc[LO+k*M]; adv=float(mark.low if s==1 else mark.high)
                adverse[k]+=s*q*(adv-t['entry'])
            # Opening exits were active during that minute before exit processing.
            active[i:min(N,j+(not intrabar))]=True
            checked_trades+=1
        for f in funding:
            t=trade_lookup[(f['symbol'],f['entry_ts'])];ts=int(f['settlement_ts']);minute=int(f['minute_ts'])
            assert minute==ts//M*M
            raw=market_io.load_funding(t['contract'],minute,minute+M)
            rates=raw.loc[raw.ts.eq(ts),'last_funding_rate'];assert len(rates)==1
            near(f['rate'],rates.iloc[0])
            mark=market_io.load_mark(t['contract'],minute,minute+M)
            near(f['mark_open'],mark.open.iloc[0])
            signed=f['side']*f['qty']*f['mark_open']*f['rate']
            near(f['signed_charge'],signed)
            near(f['actual_charge'],max(0,signed) if f['boundary_ambiguous'] else signed)
            fi=(minute-LO)//M;changes[fi]-=f['actual_charge'];stress_cash[fi]-=f['actual_charge']
            checked_fund+=1
        for t in trades:near(t['funding'],sum(f['actual_charge'] for f in funding if f['symbol']==t['symbol'] and f['entry_ts']==t['entry_ts']))
        reconstructed=1000+np.cumsum(changes)[:N]+unreal
        err=float(np.max(abs(reconstructed-curve.equity.to_numpy())))
        near(reconstructed,curve.equity,atol=2e-8)
        assert np.array_equal(expected_positions,curve.positions)
        assert np.array_equal(active,curve.active_in_minute)
        peak=np.maximum.accumulate(np.r_[1000,reconstructed])[1:]
        dd=100*(1-reconstructed/peak)
        near(dd,curve.drawdown);near(float(dd.max()),summary['max_drawdown'])
        stress_eq=1000+np.cumsum(stress_cash)[:N]+adverse
        previous_peak=np.maximum.accumulate(np.r_[1000,reconstructed])[:-1]
        stressdd=float(np.maximum(0,100*(1-stress_eq/previous_peak)).max())
        near(stressdd,summary['intrabar_stress_dd'])
        near(reconstructed[-1],1000+sum(t['net'] for t in trades))
        assert summary['annualized_return_pct'] is None and summary['elapsed_days']==300
        assert summary['signal_candidates']==len(signals)
        halt=summary['permanent_pause_ts']
        if halt is not None:
            assert all(t['entry_ts']<halt for t in trades)
            ix=(halt-LO)//M
            assert curve.permanent_paused.iloc[ix:].all()
            assert np.allclose(curve.equity.iloc[max((t['exit_ts']-LO)//M for t in trades)+1:],reconstructed[-1])
        results.append({'scenario':case,'trades':len(trades),'funding_events':len(funding),
            'net_return_pct':summary['return_pct'],'max_drawdown_pct':summary['max_drawdown'],
            'stress_drawdown_pct':stressdd,'curve_max_abs_error_usdt':err,'calendar_minutes':N,
            'full_ledger_source_exit_and_entry_checks_passed':True,'permanent_halt_ts':halt})
    audit={'completed_utc':datetime.now(timezone.utc).isoformat(),'all_checks_passed':True,
        'scenarios':results,'total_trade_ledger_checks':checked_trades,'total_funding_source_checks':checked_fund,
        'none_pass_branch_preserved':True,'same_baseline_alias_verified':report['baseline_comparison']['aligned_same_ids'],
        'engine_sha256':sha(ACC/'engine.py'),'final_execution_freeze_sha256':sha(ACC/'execution_freeze.json'),
        'scope_limit':'OHLC minute simulation and mark stress proxy; no live fill, historical tick/step or liquidation validation.'}
    (ROOT/'account_independent.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit))

if __name__=='__main__':main()
