"""Build causally available 5s features and isolated net-return training labels."""
import gc,importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
spec=importlib.util.spec_from_file_location('r23_available_features',PARENT/'第二十三轮_大突破柱预判'/'features.py')
featuremod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=featuremod;spec.loader.exec_module(featuremod)
FEATURES=featuremod.FEATURES+['estimated_stop_fraction','log_hourly_rvol','side_feature']
def build(year):
    d=featuremod.build(year)
    fill=d.raw_entry_5s*(1+d.side*.0005)
    d['estimated_stop_fraction']=d.side*(fill-d.stop_price)/fill
    d['log_hourly_rvol']=np.log(d.rvol.where(d.rvol>0))
    d['side_feature']=d.side.astype(float)
    good=np.isfinite(d[FEATURES].to_numpy(float)).all(axis=1)&d.estimated_stop_fraction.gt(0)
    d=d[good].copy()
    assert d.observation_id.is_unique and (d.model_feature_known_ts==d.entry_exec_ts).all()
    return d
def main():
    data=build(2024);cutoff=int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)
    data=data[data.decision_ts.lt(cutoff-24*60*60_000)].copy()
    r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    sc={'id':'unit_label','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,'leverage':20,'stop_shock':0.}
    records=[];excluded=[]
    for n,(_,r) in enumerate(data.iterrows(),1):
        t=pd.Timestamp(int(r.ts),unit='ms',tz='UTC');start=t.strftime('%Y-%m-%d');end=(t+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        one=pd.DataFrame([r.to_dict()]).drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
        sm,_,trades,entries,funding=touch.engine.simulate(sc,one,start,end,market=market,guard=guard,save=False,run_id='unit_label')
        if not sm['valid_for_comparison']:raise RuntimeError(f"unit_invalid:{r.observation_id}:{sm['issues']}")
        if not trades:
            excluded.append({'id':r.observation_id,'reason':'entry_rejected','details':sm['rejection_counts']});continue
        assert len(trades)==len(entries)==1
        t=trades[0]
        if t['exit_ts']>=cutoff or t['reason']=='period_end':raise RuntimeError('invalid_label_end')
        assert abs(sum(x['actual_charge'] for x in funding)-t['funding'])<1e-8
        row={'observation_id':r.observation_id,'entry_ts':t['entry_ts'],'exit_ts':t['exit_ts'],
             'net_win':int(t['net']>0),'net_pct_notional':100*t['net']/t['entry_notional'],
             'net_usdt':t['net'],'notional':t['entry_notional'],'funding':t['funding'],'exit_reason':t['reason']}
        row.update({f:float(r[f]) for f in FEATURES});records.append(row)
        if n%50==0:print('PROFIT_LABELS',n,'/',len(data),'accepted',len(records),flush=True)
    labels=pd.DataFrame(records).sort_values('entry_ts').reset_index(drop=True)
    assert labels.observation_id.is_unique and np.isfinite(labels[FEATURES].to_numpy()).all()
    labels.to_parquet(HERE/'2024独立机会净收益标签.parquet',index=False)
    meta={'source_events':len(data),'accepted_labels':len(labels),'wins':int(labels.net_win.sum()),
          'excluded_count':len(excluded),'exclusions':excluded,'features':FEATURES,
          'note':'Isolated opportunity labels, including fees/slippage/funding; shared-account evaluation is separate.'}
    flow.dump(HERE/'标签生成记录.json',meta)
    print('PROFIT_LABELS_COMPLETE',len(labels),'wins',meta['wins'],'excluded',len(excluded),flush=True)
if __name__=='__main__':main()
