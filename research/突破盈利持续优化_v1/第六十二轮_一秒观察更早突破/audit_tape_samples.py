"""Independent scalar reconstruction of selected 1s observation paths."""
import json,math,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import run_observation as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as stream,audit_retest_samples as retest_audit
sys.path.insert(0,str(P/'第三十三轮_动态池逐笔执行'));import extract_dynamic_tapes as source
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def replay(e,tape,bars,want):
    minute=int(e['trigger_minute']);qend=int(e['quarter_end']);seq=list(zip(tape.transact_time.astype('int64'),tape.price.astype(float)))
    prior=bars.reindex(range(int(e['quarter_start']),minute,60000))
    if len(prior):assert np.isfinite(prior[['high','low']].to_numpy(float)).all() and not (prior.high>e['upper']).any() and not (prior.low<e['lower']).any()
    first=tape[(tape.transact_time>=minute)&(tape.transact_time<minute+60000)];b=bars.loc[minute]
    actual=[first.price.iloc[0],first.price.max(),first.price.min(),first.price.iloc[-1]]
    assert all(near(x,b[k]) for x,k in zip(actual,('open','high','low','close')))
    cross=next((x for x in seq if x[0]<minute+60000 and (x[1]>e['upper'] or x[1]<e['lower'])),None);assert cross
    side=1 if cross[1]>e['upper'] else -1
    if not bool(e['long_known_eligible' if side==1 else 'short_known_eligible']):
        assert want['status']=='first_direction_ineligible' and want['side']==side;return 0
    if cross[0]+1000>=qend:assert want['status']=='no_order_time';return 0
    ref=next((x for x in seq if x[0]>=cross[0]+1000),None)
    if ref is None:assert want['status']=='missing_one_second_reference';return 0
    if ref[0]>=qend:assert want['status']=='no_order_time';return 0
    window=tape[(tape.transact_time>cross[0])&(tape.transact_time<cross[0]+1000)];maker=window.is_buyer_maker.astype(str).str.lower()
    values=window.price.to_numpy(float)*window.quantity.to_numpy(float);assert maker.isin(['true','false']).all()
    buy=float(values[maker.eq('false').to_numpy()].sum());sell=float(values[maker.eq('true').to_numpy()].sum())
    imbalance=side*(buy-sell)/(buy+sell) if buy+sell>0 else None
    spec=json.loads(e['long_spec'] if side==1 else e['short_spec']);level=float(spec['level']);stop=float(spec['stop_price'])
    assert int(want['decision_ts'])==cross[0] and near(want['signal_close'],cross[1]) and int(want['entry_exec_ts'])==ref[0]
    assert near(want['raw_entry_1s'],ref[1]) and want['one_count']==len(window) and near(want['buy_notional'],buy) and near(want['sell_notional'],sell)
    if len(window)<3 or imbalance is None or imbalance<.10 or side*(ref[1]-level)<=0:
        assert want['status']=='flow_filter_not_met';return 0
    assert near(want['one_imbalance'],imbalance);checks={}
    for lev in (10,20):
        checks[str(lev)]=retest_audit.manual_pre(side,ref[1],ref[0],cross[1],stop,float(e['atr']),qend,lev)
        assert want['prechecks'][str(lev)]==checks[str(lev)]
    if all(x!='passed' for x in checks.values()):assert want['status']=='known_risk_rejected';return 0
    assert want['status']=='qualified';checked=0
    for lev in (10,20):
        if checks[str(lev)]!='passed':continue
        path=want['paths'][f'one_observation_2r_{lev}x'];entry=next((x for x in seq if x[0]>=ref[0]+1000),None)
        if entry is None:assert path['status']=='missing_delayed_entry';continue
        if entry[0]>=qend:assert path['status']=='entry_after_quarter_end';continue
        fill=entry[1]*(1+side*.0005);risk=side*(fill-stop)
        invalid=risk<=0 or risk>1.5*float(e['atr']) or side*(fill-cross[1])>.25*float(e['atr']) or risk/fill+.003>=.5*(1/lev-.01)
        if invalid:signal=entry[0];reason='filled_beyond_risk_budget'
        else:
            target=fill+side*2*risk;signal=qend;reason='quarter_time';i=0
            while i<len(seq):
                t=seq[i][0];j=i+1
                while j<len(seq) and seq[j][0]==t:j+=1
                if entry[0]<=t<=qend:
                    prices=[p for _,p in seq[i:j]]
                    if any(side*(p-stop)<=0 for p in prices):signal=t;reason='stop';break
                    if any(side*(p-target)>=0 for p in prices):signal=t;reason='target';break
                if t>qend:break
                i=j
        exit=next((x for x in seq if x[0]>=signal+5000),None)
        if exit is None:assert path['status']=='missing_delayed_exit';continue
        assert path['status']=='verified' and int(path['entry_ts'])==entry[0] and near(path['entry_raw'],entry[1]) and near(path['entry_fill'],fill)
        assert int(path['exit_signal_ts'])==signal and int(path['exit_ts'])==exit[0] and path['reason']==reason
        assert near(path['exit_raw'],exit[1]) and near(path['exit_fill'],exit[1]*(1-side*.0005));checked+=1
    return checked
def main(year):
    test=json.loads((H/'独立重放合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['audit_code_sha256']==runner.sha(Path(__file__)) and test['decision_code_sha256']==runner.sha(H/'one_second_observation.py')
    candidates,baseline,paths,proof=runner.inputs(year);d=candidates[candidates.observation_id.isin(proof)]
    fp=runner.fingerprint(year);work=ROOT/'work'/f'oneobs62_{year}'/'tape';available=[]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));f=work/(runner.key(fp,spec)+'.json')
        if not f.exists():continue
        cp=json.loads(f.read_text(encoding='utf-8'))
        for row in cp['rows']:
            if row['status'] not in ('first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'):continue
            e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict();available.append((e,cp,row))
    available.sort(key=lambda x:(sum(int(a.get('bytes',0)) for a in x[1]['archives'] if a['kind']=='aggTrades'),x[0]['observation_id']));chosen=[]
    for status in ('qualified','flow_filter_not_met','known_risk_rejected'):
        x=next((v for v in available if v[2]['status']==status),None)
        if x and x not in chosen:chosen.append(x)
    for cohort in ('opening','touch'):
        x=next((v for v in available if v[0]['cohort']==cohort and v not in chosen),None)
        if x and len(chosen)<5:chosen.append(x)
    assert len(chosen)>=3;results=[]
    for e,cp,row in chosen:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        obs=e['observation_id'];body,meta=source.archive('klines',e['contract'],e['day']);bars=source.minute_bars(body,e['day']);del body
        assert meta['sha256']==proof[obs]['daily_sha256'];blocks=[];archives=[]
        for a in (x for x in cp['archives'] if x['kind']=='aggTrades'):
            got,arc=stream.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60000)},guard)
            assert arc['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(arc)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        n=replay(e,tape,bars,row);results.append({'observation_id':obs,'status':row['status'],'paths_checked':n,'archives':archives})
        print('OBS62_SAMPLE',year,len(results),'/',len(chosen),flush=True)
    out={'all_checks_pass':True,'year':year,'samples':results,'paths_checked':sum(x['paths_checked'] for x in results),
         'note':'Scalar replay of first cross, 1s flow, prechecks and exit; same-exchange public prints only.'}
    (H/f'{year}一秒观察逐笔独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_SAMPLE_PASS',year,len(results),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
