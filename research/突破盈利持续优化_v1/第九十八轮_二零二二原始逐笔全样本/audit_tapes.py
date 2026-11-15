"""Independently parse and scalar-check the 12 precommitted raw-tape samples."""
import json
import math
from pathlib import Path
import sys
import pandas as pd
import requests
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; P=H.parent
sys.path.insert(0,str(bulk.R90)); import audit_tapes_2022
sys.path.insert(0,str(bulk.R93)); import audit_raw_samples
sys.path.insert(0,str(P/'第六十二轮_一秒观察更早突破')); import audit_tape_samples


def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)


def main():
    bulk.runner.guard(start=True); frozen=bulk.frozen(); fp=bulk.fingerprint()
    d=pd.read_parquet(bulk.R90/'候选数据/固定十一币双币过滤潜在触价.parquet'); chosen=set(frozen['audit_sample_ids']); results=[]
    for (sym,day),g in d.groupby(['contract','day'],sort=True):
        if not chosen.intersection(g.observation_id): continue
        events=g.to_dict('records'); work=bulk.runner.ROOT/'raw_2022_full_checkpoints'
        path=work/(bulk.runner.key(fp,sym,day,events)+'.json'); cp=json.loads(path.read_text(encoding='utf-8'))
        assert cp['status']=='verified' and cp['fingerprint']==fp
        original=bulk.runner.WORK/(bulk.runner.key(bulk.runner.fingerprint(),sym,day,events)+'.json')
        assert bulk.sha(original)==cp['original_checkpoint_sha256']
        prev=json.loads(original.read_text(encoding='utf-8')); previous={r['observation_id']:r for r in prev['rows']}
        body,meta=bulk.runner.minutes.archive('klines',sym,day); assert meta['sha256']==cp['archives'][0]['sha256']
        bars=audit_tapes_2022.independent_bars(body,day)
        for a in cp['archives'][1:]:
            p=Path(a['path']); assert bulk.sha(p)==a['sha256']
            response=requests.get(a['url']+'.CHECKSUM',timeout=(15,50)); response.raise_for_status()
            fields=response.text.strip().split(); assert fields[0].lower()==a['sha256'] and Path(fields[1]).name==p.name
        by={r['observation_id']:r for r in cp['rows']}
        for e in events:
            obs=e['observation_id']
            if obs not in chosen:continue
            bulk.runner.guard(); want=by[obs]; status=want['status']; checked=0
            if status in ('daily_monthly_ohlc_mismatch','market_source_unknown'):
                assert previous[obs]['status']==status
            else:
                lo=int(e['trigger_minute']);hi=int(e['quarter_end'])+60000; rows=[]
                for a in cp['archives'][1:]:rows.extend(audit_raw_samples.independent_window(a['path'],'trades',lo,hi))
                rows.sort(key=lambda r:(r[0],r[1]))
                tape=pd.DataFrame([(a,b,float(c),float(d),f) for a,b,c,d,f in rows],columns=['transact_time','agg_trade_id','price','quantity','is_buyer_maker'])
                if status=='minute_trade_ohlc_mismatch':
                    first=tape[(tape.transact_time>=lo)&(tape.transact_time<lo+60000)]; assert len(first); b=bars.loc[lo]
                    actual=[first.price.iloc[0],first.price.max(),first.price.min(),first.price.iloc[-1]]
                    assert not all(near(x,b[k]) for x,k in zip(actual,('open','high','low','close')))
                elif status=='missing_event_tape': assert len(tape)==0
                elif status=='missing_trigger_ticks': assert not len(tape[(tape.transact_time>=lo)&(tape.transact_time<lo+60000)])
                elif status=='earlier_minute_cross_mismatch':
                    prior=bars.reindex(range(int(e['quarter_start']),lo,60000))
                    assert (prior.high>e['upper']).any() or (prior.low<e['lower']).any()
                else:
                    assert status in ('first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'),(obs,status)
                    checked=audit_tape_samples.replay(e,tape,bars,want)
            results.append({'observation_id':obs,'status':status,'paths_checked':checked})
            print('EXT98_TAPE_AUDIT',len(results),'/',len(chosen),status,flush=True)
    assert {x['observation_id'] for x in results}==chosen
    out={'all_checks_pass':True,'samples':results,'sample_count':len(results),'fingerprint':fp,
         'code_sha256':bulk.sha(Path(__file__)),'note':'Fixed SHA sample with independent raw parser and scalar replay; source unknowns remain unknown.'}
    (H/'原始逐笔独立抽样核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_TAPE_AUDIT_PASS',len(results),flush=True)


if __name__=='__main__':main()
