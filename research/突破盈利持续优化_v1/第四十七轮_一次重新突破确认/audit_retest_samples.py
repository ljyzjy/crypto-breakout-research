"""Independently replay four official retry tapes and their execution paths."""
import json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
import public_tape_stream as direct
H=Path(__file__).resolve().parent;P=H.parent;sys.path.insert(0,str(P/'第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as source
M=60_000
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)
def manual_pre(side,reference,reference_ts,trigger,stop,atr,qend,lev):
    if ((reference_ts//M+480)%1440)>=1320:return 'late_day_known'
    if reference_ts+5000>=qend:return 'insufficient_candle_time_known'
    estimate=reference*(1+side*.0005);distance=side*(estimate-stop);signal_distance=side*(trigger-stop)
    if side*(estimate-trigger)>.25*atr:return 'reference_deviation_known'
    if distance<=0 or distance>1.5*atr or 2*distance/estimate<.006 or 2*signal_distance/trigger<.006:return 'reference_risk_or_cost_known'
    if distance/estimate+.003>=.5*(1/lev-.01):return 'reference_liquidation_buffer_known'
    return 'passed'
def replay(e,tape,expected):
    t=tape.transact_time.to_numpy('int64');p=tape.price.to_numpy(float);side=int(e['side']);qend=int(e['quarter_end']);level=float(e['level'])
    first=np.flatnonzero((t<int(e['trigger_minute'])+M)&((p>e['upper'])|(p<e['lower'])));assert len(first)
    f=int(first[0]);assert int(t[f])==int(e['decision_ts']) and (1 if p[f]>e['upper'] else -1)==side and near(p[f],e['signal_close'])
    ref=int(np.searchsorted(t,int(t[f])+5000));assert int(t[ref])==int(e['entry_exec_ts']) and near(p[ref],e['raw_entry_5s']) and side*(p[ref]-level)<=0
    firstflow=tape[(tape.transact_time>int(t[f]))&(tape.transact_time<int(t[f])+5000)];mk=firstflow.is_buyer_maker.astype(str).str.lower()
    val=firstflow.price.to_numpy(float)*firstflow.quantity.to_numpy(float)
    assert len(firstflow)==int(e['five_count']) and near(val[mk.eq('false').to_numpy()].sum(),e['buy_notional']) and near(val[mk.eq('true').to_numpy()].sum(),e['sell_notional'])
    ii=np.flatnonzero((np.arange(len(t))>ref)&(t<qend)&(side*(p-level)>0))
    if not len(ii):assert expected['status']=='no_retest_known';return 0
    i=int(ii[0]);ts=int(t[i]);assert int(expected['retest_ts'])==ts
    if ts+5000>=qend:assert expected['status']=='no_order_time';return 0
    ref2=int(np.searchsorted(t,ts+5000))
    if ref2>=len(t):assert expected['status']=='missing_retest_reference';return 0
    if int(t[ref2])>=qend:assert expected['status']=='no_order_time';return 0
    w=tape[(tape.transact_time>ts)&(tape.transact_time<ts+5000)];m=w.is_buyer_maker.astype(str).str.lower();v=w.price.to_numpy(float)*w.quantity.to_numpy(float)
    buy=float(v[m.eq('false').to_numpy()].sum());sell=float(v[m.eq('true').to_numpy()].sum());imb=side*(buy-sell)/(buy+sell) if buy+sell>0 else None
    assert expected['five_count']==len(w) and near(expected['buy_notional'],buy) and near(expected['sell_notional'],sell)
    assert int(expected['entry_exec_ts'])==int(t[ref2]) and near(expected['raw_entry_5s'],p[ref2])
    if len(w)<3 or imb is None or imb<.10 or side*(p[ref2]-level)<=0:
        assert expected['status']=='retest_flow_filter_not_met';return 0
    assert near(imb,expected['five_imbalance']);stop=float(e['stop_price']);atr=float(e['atr']);pre={}
    for lev in (10,20):
        pre[str(lev)]=manual_pre(side,float(p[ref2]),int(t[ref2]),float(p[i]),stop,atr,qend,lev)
        assert expected['prechecks'][str(lev)]==pre[str(lev)]
    if all(x!='passed' for x in pre.values()):assert expected['status']=='known_risk_rejected';return 0
    assert expected['status']=='qualified';count=0
    for lev in (10,20):
        if pre[str(lev)]!='passed':continue
        actual=expected['paths'][f'normal_2r_{lev}x'];assert actual['status']=='verified'
        entry_idx=int(np.searchsorted(t,int(t[ref2])+5000));assert entry_idx<len(t) and t[entry_idx]<qend
        raw=float(p[entry_idx]);entry=raw*(1+side*.0005);dist=side*(entry-stop)
        bad=dist<=0 or dist>1.5*atr or side*(entry-float(p[i]))>.25*atr or dist/entry+.003>=.5*(1/lev-.01)
        if bad:signal=int(t[entry_idx]);reason='filled_beyond_risk_budget'
        else:
            target=entry+side*2*dist;choices=[(qend,3,'quarter_time')]
            for j in range(entry_idx,len(t)):
                if t[j]>qend:break
                if side*(p[j]-stop)<=0:choices.append((int(t[j]),0,'stop'));break
            for j in range(entry_idx,len(t)):
                if t[j]>qend:break
                if side*(p[j]-target)>=0:choices.append((int(t[j]),1,'target'));break
            signal,_,reason=min(choices)
        exit_idx=int(np.searchsorted(t,signal+5000));assert exit_idx<len(t)
        assert int(actual['entry_ts'])==int(t[entry_idx]) and near(actual['entry_raw'],raw) and near(actual['entry_fill'],entry)
        assert int(actual['exit_signal_ts'])==signal and int(actual['exit_ts'])==int(t[exit_idx]) and actual['reason']==reason
        assert near(actual['exit_raw'],p[exit_idx]) and near(actual['exit_fill'],p[exit_idx]*(1-side*.0005));count+=1
    return count
def main():
    import run_retests_2023 as r23,run_retests_later as later
    inputs=pd.concat([pd.read_parquet(H/'2023冻结输入'/'retry_candidates.parquet'),
       pd.read_parquet(H/'跨期冻结输入'/'2024_retry_candidates.parquet'),pd.read_parquet(H/'跨期冻结输入'/'2026_retry_candidates.parquet')],ignore_index=True).set_index('observation_id')
    available=[]
    for folder in (r23.WORK,later.WORK):
        for f in sorted(folder.glob('*.json')):
            rec=json.loads(f.read_text(encoding='utf-8'))
            if rec.get('status')!='verified':continue
            for row in rec['rows']:
                if row['status'] not in ('no_retest_known','no_order_time','retest_flow_filter_not_met','known_risk_rejected','qualified'):continue
                if row['status']=='qualified' and not all(x['status']=='verified' for x in row['paths'].values()):continue
                available.append((rec,row))
    chosen=[]
    for year in ('2023','2024','2026'):
        values=[x for x in available if str(inputs.loc[x[1]['observation_id'],'source_year'])==year]
        values.sort(key=lambda x:(x[1]['status']!='qualified',x[1]['observation_id']))
        if values:chosen.append(values[0])
    for x in sorted(available,key=lambda x:(x[1]['status']!='no_retest_known',x[1]['observation_id'])):
        if len(chosen)>=4:break
        if x[1]['observation_id'] not in [v[1]['observation_id'] for v in chosen]:chosen.append(x)
    assert len(chosen)==4
    samples=[]
    for rec,row in chosen:
        obs=row['observation_id'];e=inputs.loc[obs].to_dict();e['observation_id']=obs;blocks=[];archives=[]
        body,bar=source.archive('klines',e['contract'],e['day']);del body
        assert bar['sha256']==next(x['sha256'] for x in rec['archives'] if x['kind']=='klines')
        for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
            got,meta=direct.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)})
            assert meta['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(meta)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        count=replay(e,tape,row);samples.append({'observation_id':obs,'status':row['status'],'paths_checked':count,'archives':archives})
        print('RETEST47_INDEPENDENT_TAPE_SAMPLE',len(samples),'/4',flush=True)
    out={'all_checks_pass':True,'samples':samples,'paths_checked':sum(x['paths_checked'] for x in samples),
         'note':'Independent one-retest and delayed execution reconstruction using verified public prints.'}
    (H/'重试逐笔独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_TAPE_AUDIT_PASS',len(samples),flush=True)
if __name__=='__main__':main()
