"""Apply existing funding gate to precomputed exit-slippage scenarios."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;R55=P/'第五十五轮_WorkBuddy资金费假说';R56=P/'第五十六轮_一秒与资金费全样本复核';R59=P/'第五十九轮_退出滑点压力'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    gate=R55/'已核验机会及资金费门.csv';stress=R59/'退出滑点压力逐笔.csv';audit55=json.loads((R55/'资金费门独立核验.json').read_text(encoding='utf-8'));audit59=json.loads((R59/'退出滑点压力独立核验.json').read_text(encoding='utf-8'))
    assert audit55['all_checks_pass'] and audit55['detail_sha256']==sha(gate) and audit59['all_checks_pass'] and audit59['detail_sha256']==sha(stress)
    a=pd.read_csv(gate,dtype={'year':str});b=pd.read_csv(stress,dtype={'year':str});joined=b.merge(a[['year','leverage','observation_id','allowed']],on=['year','leverage','observation_id'],how='left',validate='many_to_one')
    assert joined.allowed.notna().all() and set(joined.allowed.unique())<={True,False}
    paired=joined[joined.allowed.eq(True)].copy();r56=json.loads((R56/'2024资金费门完整逐笔配对.json').read_text(encoding='utf-8'))['rows'];r55=json.loads((R55/'一秒入场资金费门追加对照.json').read_text(encoding='utf-8'))['rows']
    out=[]
    for year in ('2024','2026'):
        for lev in (10,20):
            ref=(next(x for x in r56 if x['leverage']==lev)['gate_one_second'] if year=='2024' else next(x for x in r55 if x['year']==year and x['leverage']==lev)['gate_one_second'])
            subset=paired[(paired.year==year)&(paired.leverage==lev)];scenarios=[]
            for slip in (.0005,.00075,.001):
                x=subset[np.isclose(subset.exit_slip,slip,rtol=0,atol=1e-12)];v=x.net.to_numpy(float);n=len(v);w=int((v>0).sum());loss=-float(v[v<0].sum())
                assert n==ref['trades'] and np.isfinite(v).all()
                item={'exit_slippage_pct':100*slip,'trades':n,'wins':w,'net_win_rate_pct':100*w/n if n else None,
                    'mean_net_pct_notional':100*float(v.mean()) if n else None,'profit_factor':float(v[v>0].sum())/loss if loss else None,
                    'unknown':16 if year=='2024' else 4}
                if slip==.0005:assert w==ref['wins'] and abs(item['mean_net_pct_notional']-ref['mean_net_pct_notional'])<1e-10
                scenarios.append(item)
            out.append({'year':year,'leverage':lev,'scenarios':scenarios})
    src=[H/'追加敏感性方案.md',Path(__file__),gate,stress,R55/'资金费门独立核验.json',R59/'退出滑点压力独立核验.json',R56/'2024资金费门完整逐笔配对.json',R55/'一秒入场资金费门追加对照.json']
    result={'rows':out,'source_sha256':{str(x):sha(x) for x in src},'note':'Post-hoc fixed-gate exit-only stress; unknowns remain unknown, not an account.'}
    (H/'资金费门退出滑点压力.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    paired.to_csv(H/'资金费门退出滑点逐笔.csv',index=False,encoding='utf-8-sig')
    print('FUNDING63_STRESS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
