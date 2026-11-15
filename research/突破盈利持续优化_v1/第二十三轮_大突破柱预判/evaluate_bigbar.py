"""Apply frozen 2024 candle model to already-studied 2026 account scenarios."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import expit
from features import build,FEATURES
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
flow.HERE=HERE;flow.eng=flow.load('bigbar_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
flow.candidate=lambda s,n:s[s.model_selected].copy()
model_path=HERE/'固定大柱预判模型.json';model=json.loads(model_path.read_text(encoding='utf-8'))
assert model['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert model['training_sha256']==hashlib.sha256((HERE/'训练特征与事后大柱标签.parquet').read_bytes()).hexdigest()
assert model['features']==FEATURES and model['threshold']==.3
model_sha=hashlib.sha256(model_path.read_bytes()).hexdigest()
s=build(2026)
raw=s[FEATURES].to_numpy(float);x=np.clip((raw-np.array(model['mean']))/np.array(model['scale']),-5,5)
s['predicted_large_probability']=expit(np.column_stack([np.ones(len(x)),x])@np.array(model['coefficients']))
s['model_selected']=s.predicted_large_probability.ge(model['threshold'])
s.to_parquet(HERE/'2026冻结模型预测与事后标签.parquet',index=False)
counts={'eligible_events':len(s),'selected_events':int(s.model_selected.sum()),
        'selected_large_bars_ex_post':int((s.model_selected&s.large_1pct_label.astype(bool)).sum()),
        'max_predicted':float(s.predicted_large_probability.max()) if len(s) else None,
        'median_predicted':float(s.predicted_large_probability.median()) if len(s) else None,
        'model_sha256':model_sha,'warning':'Observed 2026 elsewhere in project; probabilities not calibrated and labels known after candle close.'}
flow.dump(HERE/'模型预测与事后诊断.json',counts)
r2.configure(2026);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
results=[]
for name,target,partial in [('bigbar_model_1r',1.,False),('bigbar_model_partial_2r',2.,True)]:
    for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
        results.append(flow.simulate(s,name,'2026-05-01','2026-07-31',market,guard,lev,scenario,'model_2026',
                                     target_override=target,partial_exit=partial))
main=[v for v in results if v['position_leverage']==20 and v['scenario']=='main']
passed=[v for v in main if v['valid_for_comparison'] and v['trades']>=30 and v['net_win_rate_pct'] is not None
        and v['net_win_rate_pct']>=60 and v['net_pnl']>0 and v['profit_factor'] is not None and v['profit_factor']>1]
assert hashlib.sha256(model_path.read_bytes()).hexdigest()==model_sha
flow.dump(HERE/'模型账户结果.json',results)
decision={'screen_passed':bool(passed),'selected':max(passed,key=lambda v:v['net_pnl'])['run_id'] if passed else None,
          'model_sha256':model_sha,'counts':counts,'note':'Screen only; prior project use of 2026 prevents blind validation.'}
flow.dump(HERE/'模型账户筛选决定.json',decision)
print('BIGBAR_EVALUATION_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
