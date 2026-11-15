"""Compare delayed stop exits with an explicitly idealized stop-price fill."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    rows=[];details=[];sources=[H/'诊断口径.md',Path(__file__)]
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';manifest=R58/f'{year}输入冻结哈希.json';f=json.loads(manifest.read_text(encoding='utf-8'))
        assert all(sha(I/n)==v for n,v in f['inputs'].items())
        sources.extend([manifest,I/'pair_summary.json',I/'pair_details.parquet',I/'ledger_2r.parquet',I/'ledger_audit.json'])
        assert json.loads((I/'ledger_audit.json').read_text(encoding='utf-8'))['all_checks_pass']
        pairs=pd.read_parquet(I/'pair_details.parquet');ledger=pd.read_parquet(I/'ledger_2r.parquet');summary=json.loads((I/'pair_summary.json').read_text(encoding='utf-8'))['rows']
        for lev in (10,20):
            ref=next(x for x in summary if x['leverage']==lev);ids=set(pairs.loc[pairs.leverage.eq(lev),'observation_id'])
            d=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')&ledger.observation_id.isin(ids)&ledger.reason.eq('stop')]
            assert d.risk_status.eq('verified').all() and not d.liq_proxy.any() and not d.observation_id.duplicated().any()
            actual=[];ideal=[];gaps=[]
            for x in d.itertuples(index=False):
                entry=float(x.entry_fill);side=int(x.side);stop=float(x.initial_stop);exit_ideal=stop*(1-side*.0005)
                net_ideal=side*(exit_ideal-entry)/entry-.0005-(exit_ideal/entry)*.0005-float(x.funding)
                net=float(x.net_per_unit_notional);gap=net_ideal-net;actual.append(net);ideal.append(net_ideal);gaps.append(gap)
                details.append({'year':year,'leverage':lev,'observation_id':x.observation_id,'ideal_stop_fill':exit_ideal,
                    'ideal_stop_net':net_ideal,'actual_net':net,'extra_loss':gap})
            a=np.asarray(actual,float);v=np.asarray(ideal,float);g=np.asarray(gaps,float);n=len(a)
            rows.append({'year':year,'leverage':lev,'known_stop_trades':n,'worse_than_ideal_count':int((g>1e-12).sum()),
                'avg_actual_pct_notional':100*float(a.mean()) if n else None,'avg_ideal_pct_notional':100*float(v.mean()) if n else None,
                'avg_extra_loss_pct_notional':100*float(g.mean()) if n else None,'worst_actual_pct_notional':100*float(a.min()) if n else None,
                'largest_extra_loss_pct_notional':100*float(g.max()) if n else None,
                'largest_extra_loss_pct_assumed_margin':100*lev*float(g.max()) if n else None,'original_unknown':ref['paired_unknown']})
    out={'rows':rows,'source_sha256':{str(p):sha(p) for p in sources},
         'note':'Idealized stop price is not an achievable fill; comparison uses identical realized-model funding and no account.'}
    (H/'止损退出价格差距.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(details).to_csv(H/'止损退出价格差距逐笔.csv',index=False,encoding='utf-8-sig')
    print('STOP_GAP64',json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
