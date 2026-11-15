"""Independently replay each progress decision and resettled risk path."""
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';B=R98/'原始逐笔批次';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk
sys.path.insert(0,str(bulk.R93));import audit_raw_samples
from run_exit import risk_inputs


def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def audit_risk(r,marks,funds,statuses):
    side=int(r['side']);entry=float(r['entry_fill']);exit=float(r['exit_fill']);qty=1/entry;start=int(r['entry_ts']);end=int(r['exit_ts'])
    funding=0.;extremes=[]
    for ts in range(start//60000*60000,end//60000*60000+60000,60000):
        month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
        assert statuses[('markPriceKlines',r['contract'],month)]==statuses[('fundingRate',r['contract'],month)]=='verified'
        m=marks[(r['contract'],ts)];extremes.append(float(m['low' if side==1 else 'high']))
        fs=sorted(funds[(r['contract'],month)],key=lambda x:int(x['ts']));assert fs
        before=[x for x in fs if x['ts']<=ts];after=[x for x in fs if x['ts']>ts]
        low=before[-1] if before else fs[0];high=after[0] if after else fs[-1]
        allowance=max(low['funding_interval_hours'],high['funding_interval_hours'])*3600000*1.5
        gap=high['ts']-low['ts'] if before and after else fs[0]['ts']-ts if not before else ts-fs[-1]['ts']
        assert gap<=allowance
        for f in fs:
            ft=int(f['ts'])
            if ft//60000*60000==ts and start<=ft<=end:
                amount=side*qty*float(m['open'])*float(f['last_funding_rate'])
                funding+=max(0.,amount) if ft in (start,end) else amount
    net=side*qty*(exit-entry)-.0005-qty*exit*.0005-funding
    lev=int(r['variant'].rsplit('_',1)[1].rstrip('x'))
    proxy=any(1/lev-.0005-max(funding,0.)+side*qty*(v-entry)<=qty*v*.01 for v in extremes)
    assert near(r['funding'],funding) and near(r['net_per_unit_notional'],net) and bool(r['liq_proxy'])==proxy
    assert near(r['entry_fee'],.0005) and near(r['exit_fee'],qty*exit*.0005)


def main():
    bulk.runner.guard(start=True);meta=json.loads((H/'进展退出回放质量.json').read_text(encoding='utf-8'))
    assert meta['code_sha256']==bulk.sha(H/'run_exit.py') and meta['engine_sha256']==bulk.sha(H/'time_stop.py')
    assert meta['ledger_sha256']==bulk.sha(H/'进展退出单位账本.parquet') and meta['frozen_sha256']==bulk.sha(H/'研究冻结.json')
    got=pd.read_parquet(H/'进展退出单位账本.parquet').set_index(['observation_id','variant']).to_dict('index')
    baseline=pd.read_parquet(B/'单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    log={(x['observation_id'],x['variant']):x for x in meta['cases']};assert len(got)==len(log)==meta['candidate_paths']
    byobs={}
    for obs,var in got:byobs.setdefault(obs,[]).append(var)
    candidates=pd.read_parquet(bulk.R90/'候选数据/固定十一币双币过滤潜在触价.parquet')
    marks,funds,statuses=risk_inputs();checked=0;settled=0
    for (sym,day),g in candidates.groupby(['contract','day'],sort=True):
        if not set(g.observation_id).intersection(byobs):continue
        bulk.runner.guard();events=g.to_dict('records');cp_path=bulk.runner.ROOT/'raw_2022_full_checkpoints'/(bulk.runner.key(bulk.fingerprint(),sym,day,events)+'.json')
        cp=json.loads(cp_path.read_text(encoding='utf-8'));assert cp['fingerprint']==bulk.fingerprint()
        arcs=[a for a in cp['archives'] if a['kind']=='trades']
        for e in events:
            obs=e['observation_id'];variants=byobs.get(obs,[])
            if not variants:continue
            old=[baseline[(obs,v)] for v in variants]; to_check=[r for r in old if int(r['exit_signal_ts'])>int(r['entry_ts'])+30000]
            seq=[]
            if to_check:
                lo=min(int(r['entry_ts']) for r in to_check);hi=max(int(r['exit_ts']) for r in to_check)+1
                for a in arcs:
                    assert bulk.sha(a['path'])==a['sha256']
                    seq.extend(audit_raw_samples.independent_window(a['path'],'trades',lo,hi))
                seq.sort(key=lambda r:(r[0],r[1]))
            for var in variants:
                key=(obs,var);original=baseline[key];new=got[key];want=log[key]
                start=int(original['entry_ts']);signal=int(original['exit_signal_ts']); threshold=start+30000
                if signal<=threshold:action='original';reason='original_signal_first';point=None
                else:
                    point=next((x for x in seq if x[0]>=threshold),None)
                    if point is None:action='unknown';reason='missing_check_trade'
                    elif point[0]>=signal:action='original';reason='original_signal_first'
                    else:
                        progress=D(int(original['side']))*(point[2]-D(str(original['entry_fill'])))/D(str(original['actual_entry_risk']))
                        if progress>=D('.25'):action='original';reason='progress_sufficient'
                        else:
                            executed=next((x for x in seq if x[0]>=point[0]+5000),None)
                            action='early_exit' if executed is not None else 'unknown'
                            reason='insufficient_30s_progress' if executed is not None else 'missing_delayed_exit'
                assert (want['action'],want['reason'])==(action,reason) and new['time_stop_action']==action
                if action=='early_exit':
                    assert int(new['exit_signal_ts'])==point[0] and int(new['exit_ts'])==executed[0]
                    assert near(new['exit_raw'],executed[2]) and near(new['exit_fill'],float(executed[2])*(1-int(original['side'])*.0005))
                    assert int(new['exit_ts'])<=int(original['exit_ts'])
                elif action=='original':
                    for k in ('entry_ts','exit_signal_ts','exit_ts'):assert int(new[k])==int(original[k])
                    for k in ('entry_fill','exit_raw','exit_fill','net_per_unit_notional'):assert near(new[k],original[k])
                else:assert new['risk_status']=='time_stop_unknown'
                if new['risk_status']=='verified':
                    rec={**new,'observation_id':obs,'variant':var};audit_risk(rec,marks,funds,statuses);settled+=1
                checked+=1
            print('EXT100_AUDIT',checked,'/',len(got),sym,day,flush=True)
    assert checked==len(got)
    out={'all_checks_pass':True,'paths_checked':checked,'risk_settlements_checked':settled,
         'source_sha256':bulk.sha(H/'进展退出回放质量.json'),'ledger_sha256':bulk.sha(H/'进展退出单位账本.parquet'),
         'code_sha256':bulk.sha(Path(__file__)),'note':'Independent chunk parser and scalar progress/fee/funding/mark arithmetic, conditional on audited source caches.'}
    (H/'进展退出独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT100_AUDIT_PASS',checked,settled,flush=True)


if __name__=='__main__':main()
