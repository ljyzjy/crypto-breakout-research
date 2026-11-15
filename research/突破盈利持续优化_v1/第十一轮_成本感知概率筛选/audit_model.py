"""Check training cutoff, frozen prediction arithmetic, and sample labels."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
R2=PARENT/'第二轮_成本空间与即时成交';R8=PARENT/'第八轮_BTC短时领先';R9=PARENT/'第九轮_突破后延长持仓'
for p in (PARENT,R2,R8,R9,HERE):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_extended as extended
from build_training_labels import FEATURES

model=json.loads((HERE/'固定预测模型.json').read_text(encoding='utf-8'))
labels=pd.read_parquet(HERE/'训练期已完成单笔标签.parquet')
assert model['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert model['training_sha256']==hashlib.sha256((HERE/'训练期已完成单笔标签.parquet').read_bytes()).hexdigest()
assert len(labels)==model['training_count'] and labels.target.sum()==model['training_wins']
assert labels.observation_id.is_unique and (labels.entry_ts<labels.exit_ts).all()
assert labels.exit_ts.lt(int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)).all()
features_checked=0;label_samples=0
for year,tag in [(2023,'later'),(2024,None)]:
    name=f'{year}触价前市场特征'+(f'_{tag}' if tag else '')+'.parquet'
    source=pd.read_parquet(R8/name).set_index('observation_id')
    a=labels[labels.source_year.eq(year)].set_index('observation_id')
    for ident,row in a.iterrows():
        s=source.loc[ident];side=float(s.side);fill=s.raw_entry_5s*(1+side*.0005)
        expected=[side*s.prior_body_atr,np.log(s.prior_prefix_ratio),s.atr/s.level,
            (s.trigger_minute-s.quarter_start)/60_000,side*(s.signal_close-s.level)/s.atr,
            side*(s.raw_entry_5s-s.signal_close)/s.atr,side*(fill-s.stop_price)/fill,
            side*s.btc_prev_return,side*s.eth_prev_return,side*s.asset_prev_return,np.log(s.rvol),side]
        assert np.allclose(row[FEATURES].to_numpy(float),expected,rtol=1e-10,atol=1e-12)
        features_checked+=1
    ids=a.index[np.unique(np.linspace(0,len(a)-1,min(3,len(a)),dtype=int))]
    r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    sc={'id':'audit','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,
        'leverage':20,'stop_shock':0.,'max_hold_minutes':240,'allow_overnight':True}
    for ident in ids:
        record=source.loc[ident];ts=pd.Timestamp(int(record.ts),unit='ms',tz='UTC')
        one=pd.DataFrame([record.to_dict()]);one['observation_id']=ident
        one=one.drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
        sm,_,trades,_,_=extended.engine.simulate(sc,one,ts.strftime('%Y-%m-%d'),
             (ts+pd.Timedelta(days=1)).strftime('%Y-%m-%d'),market=market,guard=guard,save=False)
        assert sm['valid_for_comparison'] and len(trades)==1
        t=trades[0];expected=a.loc[ident]
        assert t['entry_ts']==expected.entry_ts and t['exit_ts']==expected.exit_ts
        assert np.isclose(t['net'],expected.net_usdt_unit_account,atol=1e-10)
        assert np.isclose(100*t['net']/t['entry_notional'],expected.net_pct_notional,atol=1e-10)
        label_samples+=1
pred_checked=0
for year,paths in [(2024,[R8/'2024触价前市场特征_later.parquet']),
                   (2026,[R8/'2026触价前市场特征.parquet',R8/'2026触价前市场特征_later.parquet'])]:
    source=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True).set_index('observation_id')
    pred=pd.read_parquet(HERE/f'{year}冻结模型预测.parquet').set_index('observation_id')
    for ident,r in pred.iterrows():
        s=source.loc[ident];side=float(s.side);fill=s.raw_entry_5s*(1+side*.0005)
        raw=np.array([side*s.prior_body_atr,np.log(s.prior_prefix_ratio),s.atr/s.level,
            (s.trigger_minute-s.quarter_start)/60_000,side*(s.signal_close-s.level)/s.atr,
            side*(s.raw_entry_5s-s.signal_close)/s.atr,side*(fill-s.stop_price)/fill,
            side*s.btc_prev_return,side*s.eth_prev_return,side*s.asset_prev_return,np.log(s.rvol),side],float)
        if not np.isfinite(raw).all():assert not r.model_selected;continue
        x=np.r_[1.,np.clip((raw-np.array(model['mean']))/np.array(model['scale']),-5,5)]
        prob=expit(x@np.array(model['logistic_coefficients']));net=x@np.array(model['ridge_coefficients'])
        assert np.isclose(prob,r.predicted_net_win_probability,rtol=1e-11)
        assert np.isclose(net,r.predicted_net_pct_notional,rtol=1e-11,atol=1e-12)
        assert bool(r.model_selected)==bool(prob>=.60 and net>0)
        pred_checked+=1
results=json.loads((HERE/'冻结模型后续账户对照.json').read_text(encoding='utf-8'))
assert all(x['valid_for_comparison'] and x['trades']==0 and x['net_pnl']==0 and not x['acceptance_pass'] for x in results)
report={'training_labels':len(labels),'training_feature_records_rebuilt':features_checked,
        'single_trade_labels_replayed':label_samples,'predictions_independently_recomputed':pred_checked,
        'zero_trade_accounts_checked':len(results),'training_exit_cutoff_respected':True,
        'limit':'Same historical market source and account engine; training-label replay is a sample, not an external execution validation.'}
(HERE/'模型与时间独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('COST_MODEL_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
