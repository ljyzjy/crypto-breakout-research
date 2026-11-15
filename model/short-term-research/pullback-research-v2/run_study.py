from common import ROOT,SOURCE,read,dump,sha
import subprocess,sys,datetime
import pandas as pd
import engine,guard
BASE=ROOT.parent/'pullback-intraday-no-daily-cap-v1'

def main():
    reg=read(ROOT/'registration.json');spec=read(ROOT/'protocol.json')
    assert sha(ROOT/'protocol.json')==reg['protocol_sha256']
    assert all(sha(BASE/f)==h for f,h in reg['baseline_files'].items())
    assert sha(SOURCE/'data-manifest.json')==reg['source_manifest_sha256']
    subprocess.run([sys.executable,str(ROOT/'validate_rules.py')],check=True)
    if not (ROOT/'coverage.json').exists():subprocess.run([sys.executable,str(ROOT/'features.py')],check=True)
    files=['protocol.json','common.py','features.py','baseline_features.py','engine.py','guard.py','validate_rules.py','run_study.py','hourly.parquet','universe-hours.parquet','archive-validation.json']
    for key in spec['versions']:
        files += [f'runs/{key}/{name}' for name in ['protocol.json','signals.parquet','hourly-ranks.parquet','hourly.parquet','regimes.parquet','quarantine.json']]
    if not (ROOT/'frozen.json').exists():
        assert not (ROOT/'comparison.json').exists()
        dump(ROOT/'frozen.json',{'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results_seen':False,'parameter_search':False,'hashes':{f:sha(ROOT/f) for f in files}})
    assert all(sha(ROOT/f)==h for f,h in read(ROOT/'frozen.json')['hashes'].items())
    rows=[dict(read(BASE/'results/main-summary.json'),variant='baseline',label='基准：次数不限')];checks=[]
    for key,cfg in spec['versions'].items():
        engine.ROOT=ROOT/'runs'/key;guard.ROOT=engine.ROOT
        scenarios=spec['scenarios'] if key=='combined' else spec['scenarios'][:1]
        summaries=[]
        for scenario in scenarios:
            result,curve,trades,entries=engine.simulate(scenario)
            assert result['valid_for_comparison'],result['issues']
            assert abs(result['ledger_error'])<1e-7
            assert not result['rejection_counts'].get('day_trade_cap',0)
            t=pd.DataFrame(trades);a=pd.DataFrame(entries)
            if len(t):
                assert abs(t.net.sum()-(curve.equity.iloc[-1]-1000))<1e-7
                assert ((t.gross-t.fees-t.slippage-t.funding-t.net).abs()<1e-7).all()
            if len(a):
                assert (a.signal_ts<=a.ts).all() and (a.break_ts<a.touch_ts).all() and (a.touch_ts<a.signal_ts).all()
                assert (a.planned_loss<=a.known_equity*a.risk_fraction+1e-7).all()
                assert (a.aggregate_planned_loss<=a.known_equity*a.portfolio_risk_cap+1e-7).all()
                assert (a.gross_after<=a.known_equity+1e-7).all()
            result.update(variant=key,label=cfg['label']);summaries.append(result)
            rows.append(result);checks.append({'variant':key,'scenario':scenario['id'],'ledger':True,'risk':True,'timing':True,'entries':len(a)})
            print('RESULT',key,scenario['id'],round(result['return_pct'],5),round(result['max_drawdown'],5),result['trades'],flush=True)
            dump(ROOT/'comparison-progress.json',rows)
        dump(engine.ROOT/'metrics.json',summaries)
    combined=[r for r in rows if r['variant']=='combined']
    passed=all(r['return_pct']>0 and r['max_drawdown']<=15 for r in combined) and combined[0]['trades']>=100
    dump(ROOT/'comparison.json',rows)
    dump(ROOT/'validation.json',{'rules':read(ROOT/'rule-validation.json'),'account_checks':checks,'baseline_unchanged':all(sha(BASE/f)==h for f,h in reg['baseline_files'].items()),'frozen_unchanged':all(sha(ROOT/f)==h for f,h in read(ROOT/'frozen.json')['hashes'].items()),'combined_passed_screen':passed,'paper_changed':False,'parameter_search':False,'history_seen':True})
    print('STUDY COMPLETE',passed,flush=True)

if __name__=='__main__':main()
