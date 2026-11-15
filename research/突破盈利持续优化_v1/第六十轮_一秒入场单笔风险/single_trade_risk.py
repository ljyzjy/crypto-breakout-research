"""Summarize verified one-second unit paths and conditional margin arithmetic."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    rows=[];details=[];sources=[H/'单笔风险说明.md',Path(__file__)]
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';manifest=R58/f'{year}输入冻结哈希.json';f=json.loads(manifest.read_text(encoding='utf-8'))
        assert all(sha(I/n)==v for n,v in f['inputs'].items());sources.extend([manifest,I/'pair_summary.json',I/'pair_details.parquet',I/'ledger_2r.parquet',I/'ledger_audit.json'])
        assert json.loads((I/'ledger_audit.json').read_text(encoding='utf-8'))['all_checks_pass']
        summary=json.loads((I/'pair_summary.json').read_text(encoding='utf-8'))['rows'];pairs=pd.read_parquet(I/'pair_details.parquet');ledger=pd.read_parquet(I/'ledger_2r.parquet')
        for lev in (10,20):
            ref=next(r for r in summary if r['leverage']==lev);d=pairs[pairs.leverage.eq(lev)].copy();assert len(d)==ref['paired_verified']
            old=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')].set_index('observation_id');assert old.index.is_unique
            for r in d.itertuples(index=False):
                x=old.loc[r.observation_id];assert x.risk_status=='verified' and not x.liq_proxy and abs(r.one_second_net-float(x.net_per_unit_notional))<1e-12
                details.append({'year':year,'leverage':lev,'observation_id':r.observation_id,'net_pct_notional':100*r.one_second_net,'net_pct_assumed_margin':100*lev*r.one_second_net})
            v=d.one_second_net.to_numpy(float);w=v[v>0];l=v[v<0];assert np.isfinite(v).all() and len(w)==ref['one_second']['wins']
            rows.append({'year':year,'leverage':lev,'verified_trades':len(v),'wins':len(w),'losses':len(l),'zero':int((v==0).sum()),
                'mean_win_pct_notional':100*float(w.mean()) if len(w) else None,'mean_loss_pct_notional':100*float(l.mean()) if len(l) else None,
                'worst_pct_notional':100*float(v.min()) if len(v) else None,'best_pct_notional':100*float(v.max()) if len(v) else None,
                'worst_pct_assumed_isolated_margin':100*lev*float(v.min()) if len(v) else None,'unknown':ref['paired_unknown']})
    out={'rows':rows,'source_sha256':{str(p):sha(p) for p in sources},'note':'Arithmetic assumes initial isolated margin = entry notional / leverage; not account drawdown or actual fills.'}
    (H/'一秒已知机会单笔风险.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(details).to_csv(H/'一秒已知机会单笔风险.csv',index=False,encoding='utf-8-sig')
    print('SINGLE_RISK60',json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
