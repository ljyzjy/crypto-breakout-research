"""Apply the frozen funding gate to every fully replayed 2024 pair."""
import hashlib, json
from pathlib import Path

import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent; P=H.parent
FAST=P/'第五十一轮_缩短市价入场延迟'; FUND=P/'第五十五轮_WorkBuddy资金费假说'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def stats(d,col,unknown):
    v=d[col].to_numpy(float); n=len(v); wins=int((v>0).sum()); loss=-v[v<0].sum()
    return {'trades':n,'wins':wins,'win_rate_pct':100*wins/n if n else None,
            'mean_net_pct_notional':100*float(v.mean()) if n else None,
            'profit_factor':float(v[v>0].sum()/loss) if loss else None,
            'active_utc_days':len({pd.Timestamp(int(x),unit='ms',tz='UTC').date() for x in d.one_second_entry_ts}),
            'unknown':unknown,'optimistic_upper_pct':100*(wins+unknown)/(n+unknown) if n+unknown else None}
def main():
    gate_file=FUND/'已核验机会及资金费门.csv'; old_file=FUND/'一秒入场资金费门追加对照.json'
    gate_audit=json.loads((FUND/'资金费门独立核验.json').read_text(encoding='utf-8'))
    pair_file=FAST/'2024一秒五秒逐笔配对结果.parquet'; summary_file=FAST/'2024一秒五秒配对对照.json'
    risk_file=FAST/'2024一秒入场分批'/'动态池单位收益与风险.parquet'
    sample_file=FAST/'2024一秒入场逐笔独立抽查.json'; ledger_file=FAST/'2024一秒入场账本独立核验.json'
    sample=json.loads(sample_file.read_text(encoding='utf-8')); ledger=json.loads(ledger_file.read_text(encoding='utf-8'))
    assert gate_audit['all_checks_pass'] and gate_audit['detail_sha256']==sha(gate_file)
    assert sample['all_checks_pass'] and len(sample['samples'])==4
    assert ledger['all_checks_pass'] and ledger['audited_one_second_paths']==93
    gates=pd.read_csv(gate_file,dtype={'year':str}); pairs=pd.read_parquet(pair_file); risk=pd.read_parquet(risk_file)
    summary=json.loads(summary_file.read_text(encoding='utf-8'))['rows']
    old=json.loads(old_file.read_text(encoding='utf-8'))['rows']
    rows=[]; details=[]
    for lev in (10,20):
        ref=next(x for x in summary if x['leverage']==lev); pre=next(x for x in old if x['year']=='2024' and x['leverage']==lev)
        g=gates[(gates.year=='2024')&(gates.leverage==lev)]; d=pairs[pairs.leverage==lev]
        assert not g.duplicated(['observation_id','leverage']).any()
        merged=d.merge(g,on=['observation_id','leverage'],how='left',validate='one_to_one')
        assert len(merged)==ref['paired_verified'] and merged.allowed.notna().all()
        assert set(merged.allowed.unique()) <= {True,False}
        assert np.allclose(merged.five_second_net,merged.net_per_unit_notional,rtol=0,atol=1e-15)
        one=risk[risk.variant.eq(f'one_second_2r_{lev}x')].set_index('observation_id')
        assert one.index.is_unique
        for x in merged.itertuples():
            z=one.loc[x.observation_id]
            assert z.risk_status=='verified' and not z.liq_proxy and int(z.side)==int(x.side)
            assert int(z.decision_ts)==int(x.decision_ts) and int(z.entry_ts)==int(x.one_second_entry_ts)
            assert abs(float(z.net_per_unit_notional)-float(x.one_second_net))<1e-15
        unknown=ref['paired_unknown']; assert unknown==16 and len(ref['unknown_ids'])==unknown
        filtered=merged[merged.allowed.eq(True)]; before=stats(merged,'one_second_net',unknown)
        assert before['trades']==ref['one_second']['trades'] and before['wins']==ref['one_second']['wins']
        assert abs(before['mean_net_pct_notional']-ref['one_second']['mean_net_pct_notional'])<1e-10
        rows.append({'leverage':lev,'baseline_one_second':before,'gate_one_second':stats(filtered,'one_second_net',unknown),
                     'baseline_five_second':stats(merged,'five_second_net',unknown),'gate_five_second':stats(filtered,'five_second_net',unknown),
                     'known_filtered':len(merged)-len(filtered),'previous_44_group_snapshot':pre})
        details.extend(merged[['year','leverage','observation_id','side','decision_ts','allowed','one_second_entry_ts','one_second_net','five_second_net']].to_dict('records'))
    sources=[H/'追加核验方案.md',Path(__file__),gate_file,old_file,pair_file,summary_file,risk_file,sample_file,ledger_file,FUND/'资金费门独立核验.json']
    out={'rows':rows,'source_sha256':{str(p):sha(p) for p in sources},
         'note':'Post-hoc 2024 unit opportunity sensitivity, with the original unknowns retained; not a blind test or account.'}
    (H/'2024资金费门完整逐笔配对.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(details).to_csv(H/'2024资金费门完整逐笔.csv',index=False,encoding='utf-8-sig')
    print('FUNDING56_2024',json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
