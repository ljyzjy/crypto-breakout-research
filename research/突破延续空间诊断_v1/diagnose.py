"""Retrospective opportunity-level diagnostic; no order APIs or model writes."""
from __future__ import annotations
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PREV=HERE.parent/'突破柱融合研究_v1'
GE=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P2=GE/'outputs'/'feature-research-phase2'
sys.path.insert(0,str(GE/'work'/'winrate60'))
from labels import Tape,label_one
from account_market import RankTrendGuard

spec=importlib.util.spec_from_file_location('diagnostic_phase2_readonly',P2/'data_io.py')
pio=importlib.util.module_from_spec(spec);spec.loader.exec_module(pio)
M=60_000
SPLIT=int(pd.Timestamp('2026-01-01',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)

def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
        default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

def label_all(signals):
    guard=RankTrendGuard(); labels=[]; feature_rows=[]
    for contract,g in signals.groupby('contract',sort=True):
        start=int(g.ts.min()); tape=Tape(contract,start,END)
        raw=pio.load_minutes(contract,int(g.break_ts.min()),int(g.break_ts.max())+M)
        raw=raw.set_index('ts',verify_integrity=True)
        for s in g.itertuples(index=False):
            t=int(s.break_ts); boundary=SPLIT if int(s.decision_ts)<SPLIT else END
            if t not in raw.index:raise ValueError('Break minute absent: '+s.observation_id)
            bar=raw.loc[t]; width=float(bar.high-bar.low)
            body=float(int(s.side)*(float(bar.close)-float(bar.open))/width) if np.isfinite(width) and width>0 else np.nan
            extension=float(int(s.side)*(float(s.signal_close)-float(s.level))/float(s.atr))
            k=int((int(s.decision_ts)-int(s.quarter_start))//M)
            if not (1<=k<=13 and extension>0 and (not np.isfinite(body) or -1-1e-9<=body<=1+1e-9)):
                raise ValueError('Invalid known signal features: '+s.observation_id)
            activity=('not_both_active' if not s.activity_pass else
                      'active_not_sync' if not s.sync_pass else 'active_sync')
            feature_rows.append({'observation_id':s.observation_id,'decision_ts':int(s.decision_ts),
                'feature_max_known_ts':int(s.break_ts)+M,'elapsed_minute':k,
                'elapsed_group':'minute_1_to_5' if k<=5 else 'minute_6_to_13',
                'extension_atr':extension,'extension_group':'up_to_0_25_atr' if extension<=.25 else 'above_0_25_atr',
                'body_fraction':body,'body_group':('body_unknown' if not np.isfinite(body) else
                    'body_at_least_half' if body>=.5 else 'body_below_half'),
                'activity_group':activity,'activity_known':bool(s.activity_known)})
            if int(s.decision_ts)+65*M>=boundary:
                lab={'observation_id':s.observation_id,'label_status':'purged_65min_boundary',
                     'decision_ts':int(s.decision_ts),'entry_ts':int(s.ts)}
            else:
                lab=label_one(s,tape,guard,boundary)
            labels.append(lab)
        print('LABELED',contract,len(g),'total',len(labels),flush=True)
    lab=pd.DataFrame(labels); feat=pd.DataFrame(feature_rows)
    assert len(lab)==len(signals)==len(feat) and lab.observation_id.is_unique and feat.observation_id.is_unique
    assert (feat.feature_max_known_ts<=feat.decision_ts).all()
    d=feat.merge(lab.drop(columns=['decision_ts'],errors='ignore'),on='observation_id',validate='one_to_one')
    d['split']=np.where(d.decision_ts<SPLIT,'earlier','later')
    d['day']=pd.to_datetime(d.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    d.to_parquet(HERE/'全部机会与标签.parquet',index=False)
    status=d.groupby(['split','label_status'],dropna=False).size().reset_index(name='count')
    status.to_csv(HERE/'机会状态与缺失.csv',index=False,encoding='utf-8-sig')
    return d

def block_samples(dates, draws=2000, seed=20261114):
    rng=np.random.default_rng(seed); n=len(dates); length=7
    nblocks=int(np.ceil(n/length))
    starts=rng.integers(0,n-length+1,size=(draws,nblocks))
    ix=(starts[:,:,None]+np.arange(length)).reshape(draws,-1)[:,:n]
    return ix

def describe(d):
    valid=d[d.label_status.eq('valid')].copy()
    valid['net_bp']=valid.net_per_notional*10000
    valid['gross_bp']=valid.gross_per_notional*10000
    valid['cost_bp']=(valid.fees_per_notional+valid.slippage_per_notional+valid.funding_per_notional)*10000
    dimensions={'market':'activity_group','timing':'elapsed_group',
                'extension':'extension_group','body':'body_group'}
    periods={'earlier':('2025-07-01','2025-12-31'),'later':('2026-01-01','2026-04-26')}
    comparisons={'market':('active_sync','not_both_active'),
                 'timing':('minute_1_to_5','minute_6_to_13'),
                 'extension':('up_to_0_25_atr','above_0_25_atr'),
                 'body':('body_at_least_half','body_below_half')}
    result=[]; differences=[]
    for split,(begin,end) in periods.items():
        days=pd.date_range(begin,end,freq='D').strftime('%Y-%m-%d')
        x=valid[valid.split.eq(split)]
        idx=block_samples(days)
        for name,col in dimensions.items():
            boot={}
            for group,g in x.groupby(col,sort=True):
                daily=g.groupby('day').net_bp.agg(['sum','count']).reindex(days,fill_value=0)
                sums=daily['sum'].to_numpy()[idx].sum(axis=1)
                counts=daily['count'].to_numpy()[idx].sum(axis=1)
                dist=np.divide(sums,counts,out=np.full(len(sums),np.nan),where=counts>0)
                boot[group]=dist
                ci=np.nanquantile(dist,[.025,.975]) if np.isfinite(dist).any() else [np.nan,np.nan]
                result.append({'split':split,'dimension':name,'group':group,'opportunities':len(g),
                  'active_days':g.day.nunique(),'gross_bp_mean':g.gross_bp.mean(),
                  'cost_bp_mean':g.cost_bp.mean(),'net_bp_mean':g.net_bp.mean(),
                  'net_win_rate_pct':100*g.y.mean(),'median_net_bp':g.net_bp.median(),
                  'net_mean_ci95_low':ci[0],'net_mean_ci95_high':ci[1]})
            ga,gb=comparisons[name]
            if ga in boot and gb in boot:
                ba=boot[ga];bb=boot[gb]; diff=ba-bb
                ia=x[x[col].eq(ga)];ib=x[x[col].eq(gb)]
                ci=np.nanquantile(diff,[.025,.975])
                differences.append({'split':split,'dimension':name,'comparison':ga+' minus '+gb,
                    'net_bp_difference':ia.net_bp.mean()-ib.net_bp.mean(),
                    'difference_ci95_low':ci[0],'difference_ci95_high':ci[1],
                    'n_a':len(ia),'n_b':len(ib)})
    res=pd.DataFrame(result); diff=pd.DataFrame(differences)
    res.to_csv(HERE/'分组机会诊断.csv',index=False,encoding='utf-8-sig')
    diff.to_csv(HERE/'分组差异描述.csv',index=False,encoding='utf-8-sig')
    return valid,res,diff

def reconcile(d):
    lab=d.set_index('observation_id'); common=[]; exit_types={'stop','target','gap_stop','gap_target','time60','day_close'}
    for name in ['early_base','early_activity','early_sync']:
        trades=json.loads((PREV/f'{name}_main_trades.json').read_text(encoding='utf-8'))
        for t in trades:
            if t['observation_id'] not in lab.index or t['reason'] not in exit_types:continue
            row=lab.loc[t['observation_id']]
            if row.label_status!='valid':continue
            expected=t['net']/t['entry_notional']
            error=abs(expected-row.net_per_notional)
            common.append({'id':t['observation_id'],'account':name,'reason':t['reason'],
                           'net_per_notional_absolute_error':error,
                           'same_entry':int(t['entry_ts'])==int(row.entry_ts),
                           'same_exit':int(t['exit_ts'])==int(row.exit_ts)})
    if not common:raise ValueError('No comparable prior account trades for validation')
    unmatched=[r for r in common if r['net_per_notional_absolute_error']>1e-9 or not r['same_entry'] or not r['same_exit']]
    report={'comparable_account_records':len(common),'max_net_error':max(r['net_per_notional_absolute_error'] for r in common),
        'mismatch_count':len(unmatched),'mismatch_examples':unmatched[:10],
        'known_time_checks':bool((d.feature_max_known_ts<=d.decision_ts).all()),
        'interpretation':'Unit opportunity paths can overlap; account risk/capital/pause exits are not included.'}
    dump(HERE/'对账验证.json',report)
    if unmatched:raise ValueError('Label paths differ from account; see reconciliation')
    return report

def main():
    sig=pd.read_parquet(PREV/'signals.parquet').copy();sig['variant']='diagnostic'
    if sig.observation_id.duplicated().any():raise ValueError('Duplicate signal ID')
    if not sig.activity_known.all():raise ValueError('Unknown activity needs its own group')
    d=label_all(sig)
    check=reconcile(d)
    valid,res,diff=describe(d)
    result={'candidates':len(sig),'valid_independent_opportunities':len(valid),
            'status_counts':d.groupby(['split','label_status']).size().to_dict(),
            'matched_account_records':check['comparable_account_records']}
    print('DIAGNOSTIC_COMPLETE',result,flush=True)

if __name__=='__main__':main()
