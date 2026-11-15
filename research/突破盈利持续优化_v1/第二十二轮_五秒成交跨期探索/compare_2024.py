"""Descriptive 2024 vs already examined 2026 fixed-rule account comparison."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
flow.HERE=HERE;flow.eng=flow.load('crossflow_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
VARIANTS=[('cross_plain_1r',1.,False,'flow5_strong_1r',PARENT/'第十九轮_突破后五秒主动成交'),
          ('cross_plain_2r',2.,False,'flow5_strong_2r',PARENT/'第十九轮_突破后五秒主动成交'),
          ('cross_partial_2r',2.,True,'combined_partial_2r',PARENT/'第二十一轮_五秒成交与分批保护')]
def select(s,name):
    hold=s.side*(s.raw_entry_5s-s.level)>0
    return s[hold&s.flow5_status.eq('verified')&s.flow5_count.ge(3)&s.flow5_imbalance.ge(.1)].copy()
flow.candidate=select
def main():
    meta=json.loads((HERE/'五秒主动成交档案校验.json').read_text(encoding='utf-8'))
    if meta['archive_errors']:raise ValueError('flow_2024_incomplete')
    sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
    sig=sig[sig.status.eq('verified')&sig.source_year.eq('2024')].copy();sig['tick_status']='verified'
    feat=pd.read_parquet(HERE/'五秒主动成交特征_2024.parquet').rename(columns={'status':'flow5_status',
        'count':'flow5_count','directional_imbalance':'flow5_imbalance','archive_sha256':'flow_archive_sha256'})
    s=sig.merge(feat,on='observation_id',validate='one_to_one');assert len(s)==len(sig)
    valid=s[s.flow5_status.eq('verified')]
    assert (valid.last_ts<valid.window_end).all() and (valid.window_end<=valid.entry_exec_ts).all()
    r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    out=[]
    for name,target,partial,oldname,oldfolder in VARIANTS:
        for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
            sm=flow.simulate(s,name,'2024-01-01','2024-06-30',market,guard,lev,scenario,'cross_2024',
                             target_override=target,partial_exit=partial)
            old=json.loads((oldfolder/f'screen_2026_{oldname}_{lev}x_{scenario}_summary.json').read_text(encoding='utf-8'))
            fields=['trades','net_win_rate_pct','net_pnl','profit_factor','max_drawdown','active_calendar_days',
                    'liquidation_proxy_count','acceptance_pass','valid_for_comparison']
            for label,item in [('2024H1',sm),('2026MayJul',old)]:
                out.append({'variant':name,'period':label,'leverage':lev,'cost':scenario,**{k:item.get(k) for k in fields}})
    flow.dump(HERE/'五秒成交跨期账户对照.json',out)
    pd.DataFrame(out).to_csv(HERE/'五秒成交跨期账户对照.csv',index=False,encoding='utf-8-sig')
    decision={'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
      'feature_sha256':hashlib.sha256((HERE/'五秒主动成交特征_2024.parquet').read_bytes()).hexdigest(),
      'interpretation':'Exploratory cross-period comparison chosen after earlier 2026 results; not project-level blind evaluation.'}
    flow.dump(HERE/'跨期说明.json',decision)
    print('CROSSFLOW_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
