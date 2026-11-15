"""Evaluate a previously frozen 2024-Apr model against an unfiltered account."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import expit
from build_labels import build,FEATURES
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
model_path=HERE/'四月底固定净收益模型.json';model=json.loads(model_path.read_text(encoding='utf-8'))
assert model['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert model['source_label_sha256']==hashlib.sha256((HERE/'2024独立机会净收益标签.parquet').read_bytes()).hexdigest()
assert model['features']==FEATURES and model['minimum_predicted_win']==.5 and model['minimum_predicted_net_pct']==0.
assert model['last_train_exit_ts']<model['cutoff_ts']
model_hash=hashlib.sha256(model_path.read_bytes()).hexdigest()
d=build(2024);lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
hi=int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000)
d=d[d.decision_ts.ge(lo)&d.decision_ts.lt(hi)].copy()
raw=d[FEATURES].to_numpy(float);x=np.clip((raw-np.array(model['mean']))/np.array(model['scale']),-5,5)
X=np.column_stack([np.ones(len(x)),x]);d['predicted_net_win']=expit(X@np.array(model['logistic_coefficients']))
d['predicted_net_pct']=X@np.array(model['ridge_coefficients'])
d['model_selected']=d.predicted_net_win.ge(.5)&d.predicted_net_pct.gt(0)
d.to_parquet(HERE/'五月六月冻结模型预测.parquet',index=False)
selection={'eligible_events':len(d),'selected_events':int(d.model_selected.sum()),
           'predicted_win_at_least_half':int(d.predicted_net_win.ge(.5).sum()),
           'predicted_net_positive':int(d.predicted_net_pct.gt(0).sum()),
           'model_sha256':model_hash,'note':'May-June precedes 2026 but has been used in other project research.'}
flow.dump(HERE/'五月六月预测数量.json',selection)
flow.HERE=HERE;flow.eng=touch.engine
flow.candidate=lambda s,n:s[s.model_selected].copy() if n=='net_model_1r' else s.copy()
r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
results=[]
for name in ('net_model_1r','unfiltered_1r'):
    for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
        results.append(flow.simulate(d,name,'2024-05-01','2024-06-29',market,guard,lev,scenario,
                                     'val_may_jun_2024',target_override=1.))
main=next(x for x in results if x['run_id']=='net_model_1r' and x['position_leverage']==20 and x['scenario']=='main')
passed=bool(main['valid_for_comparison'] and main['trades']>=20 and main['net_win_rate_pct'] is not None and
            main['net_win_rate_pct']>=60 and main['net_pnl']>0 and main['profit_factor'] is not None and main['profit_factor']>1)
flow.dump(HERE/'五月六月账户对照.json',results)
decision={'validation_passed':passed,'model_sha256':model_hash,'selection':selection,
          'metrics':{k:main.get(k) for k in ['trades','active_calendar_days','net_win_rate_pct','net_pnl','profit_factor','max_drawdown']},
          'note':'Passing this preliminary 20-trade screen alone would not satisfy the final 100-trade objective.'}
assert hashlib.sha256(model_path.read_bytes()).hexdigest()==model_hash
flow.dump(HERE/'五月六月验证决定.json',decision)
print('NET_MODEL_VALIDATION_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
