"""Recalculate exit cost break-even from original individual ledgers."""
import csv,hashlib,json,math
from decimal import Decimal,getcontext
from pathlib import Path
import pandas as pd
getcontext().prec=32
H=Path(__file__).resolve().parent;P=H.parent;R58=P/'第五十八轮_一秒入场一倍止盈';R55=P/'第五十五轮_WorkBuddy资金费假说'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dec(x):return Decimal(str(x))
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)
def main():
    out=H/'退出滑点盈亏临界.json';z=json.loads(out.read_text(encoding='utf-8'))
    for p,d in z['source_sha256'].items():assert sha(Path(p))==d
    with (R55/'已核验机会及资金费门.csv').open(encoding='utf-8-sig',newline='') as f:
        gate={(r['year'],int(r['leverage']),r['observation_id']):r['allowed']=='True' for r in csv.DictReader(f)}
    data={}
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';pairs=pd.read_parquet(I/'pair_details.parquet');ledger=pd.read_parquet(I/'ledger_2r.parquet')
        for lev in (10,20):
            ids=set(pairs.loc[pairs.leverage.eq(lev),'observation_id']);d=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')&ledger.observation_id.isin(ids)]
            for strategy in ('base','funding_gate'):
                chosen=[r for r in d.itertuples(index=False) if strategy=='base' or gate[(year,lev,r.observation_id)]]
                data[(strategy,year,lev)]=chosen
    for row in z['rows']:
        chosen=data[(row['strategy'],row['year'],row['leverage'])];assert len(chosen)==row['trades'];zero=[];slopes=[]
        for r in chosen:
            entry=dec(r.entry_fill);raw=dec(r.exit_raw);side=dec(r.side)
            net0=side*(raw-entry)/entry-Decimal('.0005')-raw/entry*Decimal('.0005')-dec(r.funding)
            slope=raw/entry*(Decimal(1)-side*Decimal('.0005'))
            zero.append(100*net0);slopes.append(slope)
        mean0=sum(zero,Decimal(0))/len(zero);meanslope=sum(slopes,Decimal(0))/len(slopes);critical=mean0/meanslope
        assert near(mean0,row['zero_exit_slip_mean_net_pct_notional']) and near(mean0-meanslope*Decimal('.05'),row['base_mean_net_pct_notional'])
        assert row['negative_break_even_impossible_under_nonnegative_adverse_slip']==(critical<0)
        if critical>=0:assert near(critical,row['conditional_break_even_exit_slip_pct'])
        else:assert row['conditional_break_even_exit_slip_pct'] is None
    audit={'all_checks_pass':True,'groups_checked':len(z['rows']),'output_sha256':sha(out),'audit_sha256':sha(Path(__file__)),
           'note':'Direct Decimal calculation from original entry/exit ledger, conditional on unchanged signals.'}
    (H/'退出滑点盈亏临界独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BREAKEVEN65_AUDIT_PASS',json.dumps(audit,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
