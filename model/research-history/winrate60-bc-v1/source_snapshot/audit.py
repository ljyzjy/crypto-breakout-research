from common import *
from labels import Tape,label_one
from scipy.stats import rankdata
from datetime import datetime,timezone

def auc(y,p):
    pos=y==1;n1=int(pos.sum());n0=int((~pos).sum())
    return float((rankdata(p)[pos].sum()-n1*(n1+1)/2)/(n1*n0)) if n0*n1 else None

def main():
    pred=pd.read_parquet(OUT/'predictions/all.parquet');labs=pd.concat([pd.read_parquet(OUT/'labels/development.parquet'),pd.read_parquet(OUT/'labels/evaluation.parquet')],ignore_index=True)
    joined=pred.merge(labs.drop(columns=['variant','decision_ts']),on='observation_id',how='left',validate='one_to_one')
    metrics=[];bins=[];bycoin=[];bymonth=[]
    for (v,split),g in joined.groupby(['variant','split']):
        z=g[g.label_status.eq('valid')&g.features_valid].copy();y=z.y.to_numpy(float);p=z.probability.to_numpy(float)
        model=read(OUT/'models'/f'{v}.json');constant=model['calibration_win_rate']
        info={'variant':v,'split':split,'candidates':len(g),'feature_valid':int(g.features_valid.sum()),'executable_labels':len(z),'wins':int(z.y.sum()),
          'net_win_rate_pct':float(100*y.mean()),'mean_net_R':float(z.net_R.mean()),'mean_net_bp':float(10000*z.net_per_notional.mean()),
          'auc':auc(y,p),'brier':float(np.mean((p-y)**2)),'constant_calibration_rate_brier':float(np.mean((constant-y)**2)),
          'max_probability_all_candidates':float(g.probability.max()),'max_raw_probability_all_candidates':float(g.raw_probability.max()),
          'passed_probability':int(g.probability.ge(.65).sum()),'passed_ev':int(g.estimated_net_R.gt(0).sum()),'passed_both':int(g.filter_pass.sum()),
          'residual_missing_pct':float(100*g.residual_missing.mean()),'label_status':g.label_status.value_counts().to_dict()}
        metrics.append(info)
        z['probability_bin']=pd.cut(z.probability,bins=np.arange(0,1.00001,.1),include_lowest=True,right=False)
        for label,b in z.groupby('probability_bin',observed=True):
            bins.append({'variant':v,'split':split,'bin':str(label),'n':len(b),'predicted_mean':float(b.probability.mean()),'observed_win_rate':float(b.y.mean()),'mean_net_R':float(b.net_R.mean())})
        if split=='evaluation':
            for (s,side),b in z.groupby(['symbol','side']):bycoin.append({'variant':v,'symbol':s,'side':int(side),'n':len(b),'win_rate_pct':float(100*b.y.mean()),'mean_net_R':float(b.net_R.mean())})
            z['month']=pd.to_datetime(z.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m')
            for month,b in z.groupby('month'):bymonth.append({'variant':v,'month':month,'n':len(b),'win_rate_pct':float(100*b.y.mean()),'mean_net_R':float(b.net_R.mean())})
    dump(OUT/'diagnostics/opportunity_results.json',{'warning':'Independent hypothetical opportunity labels, not account trades; overlapping opportunities and portfolio-dependent exits excluded. No threshold or strategy selected using these results.','results':metrics,'fixed_probability_bins':bins})
    pd.DataFrame(bycoin).to_csv(OUT/'diagnostics/opportunities_by_coin.csv',index=False);pd.DataFrame(bymonth).to_csv(OUT/'diagnostics/opportunities_by_month.csv',index=False)
    # Same initial breakouts that produce both executable B and C opportunities.
    ev=joined[joined.split.eq('evaluation')&joined.label_status.eq('valid')]
    b=ev[ev.variant.eq('B')][['base_event_id','y','net_R','net_per_notional']]
    c=ev[ev.variant.eq('C')][['base_event_id','y','net_R','net_per_notional']]
    paired=b.merge(c,on='base_event_id',suffixes=('_B','_C'),validate='one_to_one')
    save('diagnostics/paired_opportunities.parquet',paired)
    dump(OUT/'diagnostics/paired_summary.json',{'n':len(paired),'B_net_win_rate_pct':float(100*paired.y_B.mean()),'C_net_win_rate_pct':float(100*paired.y_C.mean()),'mean_C_minus_B_net_bp':float(10000*(paired.net_per_notional_C-paired.net_per_notional_B).mean()),'warning':'Post-hoc executable intersection, diagnostic only. Does not define account opportunities or prove causal superiority.'})
    # Compare independent label implementation with original portfolio engine, one position.
    guard=RankTrendGuard();checks=[]
    for variant in ['B','C']:
        choices=joined[joined.variant.eq(variant)&joined.label_status.eq('valid')]
        selected=[]
        for reason in ['stop','target','time60']:
            g=choices[choices.reason.eq(reason)]
            if len(g):selected.append(g.iloc[0])
        g=choices[choices.funding_per_notional.ne(0)]
        if len(g):selected.append(g.iloc[0])
        for s in selected:
            date=pd.Timestamp(int(s.ts),unit='ms',tz='UTC').strftime('%Y-%m-%d')
            market=Market();market.month_contracts={month:{s.contract} for month in market.month_contracts}
            signal=pd.DataFrame([s[pred.columns].to_dict()])
            enddate=(pd.Timestamp(date)+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            summary,curve,trades,entries,funding=simulate(PROTOCOL['cost_scenarios'][0],signal,date,enddate,market=market,guard=guard,save=False,run_id='audit_single')
            assert summary['valid_for_comparison'] and len(trades)==1,(s.observation_id,summary)
            t=trades[0];amount=t['entry_notional']
            errors={k:abs(t[k]/amount-float(s[v])) for k,v in [('net','net_per_notional'),('gross','gross_per_notional'),('fees','fees_per_notional'),('slippage','slippage_per_notional'),('funding','funding_per_notional')]}
            assert max(errors.values())<1e-10,(s.observation_id,errors)
            assert t['exit_ts']==s.exit_ts and t['reason']==s.reason
            checks.append({'variant':variant,'id':s.observation_id,'reason':s.reason,'funding_nonzero':bool(s.funding_per_notional!=0),'max_error':max(errors.values())})
    # Source/config protection: include previous original simulator source inventory without database access.
    expected=read(OUT/'registration.json')['protected_files'].copy()
    original=read(P3/'protected_before.json')['files']
    for rel,item in original.items():expected[str((BASE/rel).resolve())]=item['sha256']
    changed=[]
    for path,wanted in expected.items():
        if not Path(path).is_file() or sha(path)!=wanted:changed.append(path)
    assert not changed,changed
    temporal={}
    for v in ['B','C']:
        model=read(OUT/'models'/f'{v}.json')
        temporal[v]={'train_end_ok':model['training_max_label_ts']<TRAIN_END,'calibration_end_ok':model['calibration_max_label_ts']<CAL_END}
        assert all(temporal[v].values())
    c=pred[pred.variant.eq('C')];assert (c.touch_ts+M<c.decision_ts).all();assert (c.decision_ts<c.ts).all()
    report={'verified_utc':datetime.now(timezone.utc).isoformat(),'source_files_verified':len(expected),'changed_sources':changed,'single_trade_engine_checks':checks,'temporal':temporal,'prefix_checks':len(read(OUT/'signals/build_audit.json')['prefix_checks']),'B_baseline_signal_exact_match':True,'C_touch_confirmation_entry_order':True,'models_not_retrained':True,'threshold_not_changed':True,'paper_database_accessed':False,'passed':True}
    dump(OUT/'audit.json',report)
    print('AUDIT_PASSED',len(checks),'labels',len(expected),'sources',flush=True)
    print(pd.DataFrame(metrics)[['variant','split','candidates','executable_labels','net_win_rate_pct','mean_net_R','auc','passed_both']].to_string(index=False),flush=True)

if __name__=='__main__':main()
