"""Stress adverse exit slippage while holding entry and exit signal fixed."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;R58=P/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stats(vals,unknown,days):
    x=np.asarray(vals,float);assert np.isfinite(x).all();n=len(x);wins=int((x>0).sum());loss=-float(x[x<0].sum())
    return {'trades':n,'wins':wins,'win_rate_pct':100*wins/n if n else None,
            'mean_net_pct_notional':100*float(x.mean()) if n else None,'profit_factor':float(x[x>0].sum())/loss if loss else None,
            'active_utc_days':len(days),'unknown':unknown}
def main():
    results=[];details=[];sources=[H/'冻结研究方案.md',Path(__file__)]
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';manifest=json.loads((R58/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
        assert all(sha(I/n)==v for n,v in manifest['inputs'].items())
        sources.extend([R58/f'{year}输入冻结哈希.json',I/'ledger_2r.parquet',I/'pair_details.parquet',I/'pair_summary.json',I/'ledger_audit.json'])
        assert json.loads((I/'ledger_audit.json').read_text(encoding='utf-8'))['all_checks_pass']
        ledger=pd.read_parquet(I/'ledger_2r.parquet');pairs=pd.read_parquet(I/'pair_details.parquet');summaries=json.loads((I/'pair_summary.json').read_text(encoding='utf-8'))['rows']
        for lev in (10,20):
            ref=next(x for x in summaries if x['leverage']==lev);ids=set(pairs.loc[pairs.leverage.eq(lev),'observation_id']);assert len(ids)==ref['paired_verified']
            subset=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')&ledger.observation_id.isin(ids)].copy()
            assert len(subset)==len(ids) and not subset.observation_id.duplicated().any() and subset.risk_status.eq('verified').all() and not subset.liq_proxy.any()
            days={pd.Timestamp(int(x),unit='ms',tz='UTC').date() for x in subset.entry_ts}
            scenarios=[]
            for slip in (0.0005,0.00075,0.001):
                vals=[]
                for r in subset.itertuples(index=False):
                    qty=1/float(r.entry_fill);exitfill=float(r.exit_raw)*(1-int(r.side)*slip)
                    fee=qty*exitfill*.0005;net=int(r.side)*qty*(exitfill-float(r.entry_fill))-.0005-fee-float(r.funding)
                    if slip==.0005:assert abs(net-float(r.net_per_unit_notional))<1e-11 and abs(exitfill-float(r.exit_fill))<1e-9
                    vals.append(net);details.append({'year':year,'leverage':lev,'observation_id':r.observation_id,'exit_slip':slip,
                        'exit_fill':exitfill,'exit_fee':fee,'funding':float(r.funding),'net':net})
                item={'exit_slippage_pct':slip*100,**stats(vals,ref['paired_unknown'],days)};scenarios.append(item)
            assert scenarios[0]['wins']==ref['one_second']['wins'] and abs(scenarios[0]['mean_net_pct_notional']-ref['one_second']['mean_net_pct_notional'])<1e-10
            results.append({'year':year,'leverage':lev,'scenarios':scenarios})
    out={'rows':results,'source_sha256':{str(p):sha(p) for p in sources},'note':'Exit-only stress; signals and duration unchanged. Historical unit paths, not fills or account results.'}
    (H/'退出滑点压力对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(details).to_csv(H/'退出滑点压力逐笔.csv',index=False,encoding='utf-8-sig')
    print('EXIT_SLIP59',json.dumps(results,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
