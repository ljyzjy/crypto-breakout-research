"""Independently audit every permitted tape reuse and four daily prefixes."""
import hashlib,io,json,math
from pathlib import Path
import numpy as np,pandas as pd,requests
import verify_reuse_prefixes as source
H=Path(__file__).resolve().parent;I=H/'逐笔冻结输入';ROOT=H.parent.parent.parent;M=60_000
def main():
    plan=pd.read_parquet(H/'逐笔复用计划.parquet').set_index('observation_id')
    candidates=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True).set_index('observation_id')
    old=pd.concat([pd.read_parquet(I/'old_signal.parquet'),pd.read_parquet(I/'backup_signal.parquet')],ignore_index=True).set_index('observation_id')
    prefix={}
    for p in source.WORK.glob('*.json'):
        rec=json.loads(p.read_text(encoding='utf-8'));assert rec['status']=='verified'
        ids=sorted(r['observation_id'] for r in rec['rows']);key=hashlib.sha256((source.FP+'|'+rec['contract']+'|'+rec['day']+'|'+'|'.join(ids)).encode()).hexdigest();assert p.stem==key
        for row in rec['rows']:assert row['observation_id'] not in prefix;prefix[row['observation_id']]={**row,'daily_sha256':rec['daily_sha256']}
    allowed=[]
    for obs,p in plan.iterrows():
        if p.reuse_status!='reuse_after_prefix_check':continue
        e=candidates.loc[obs];previous=old.loc[obs]
        for key in ('symbol','contract','trigger_minute','quarter_start','quarter_end','upper','lower','atr'):
            assert e[key]==previous[key],(obs,key)
        check=prefix.get(obs);assert check is not None and check['status']=='verified'
        original=json.loads(Path(check['old_checkpoint']).read_text(encoding='utf-8'))
        oldrow=next(x for x in original['rows'] if x['observation_id']==obs);assert oldrow['status']==previous['status']
        bar=next(x for x in original['archives'] if x['kind']=='klines' and x['day']==e.day)
        assert bar['sha256']==check['daily_sha256']
        side=int(previous.side);name='long' if side==1 else 'short';eligible=bool(e[name+'_known_eligible'])
        if p.reason=='new_first_direction_ineligible':assert not eligible
        elif p.reason=='same_no_order_time':assert eligible and previous.status=='no_order_time'
        else:
            assert p.reason=='exact_execution_inputs' and eligible and previous.status in ('flow_filter_not_met','known_risk_rejected','qualified')
            spec=json.loads(e[name+'_spec'])
            assert float(spec['stop_price'])==float(previous.stop_price) and float(spec['level'])==float(previous.level)
        allowed.append(obs)
    assert len(allowed)==len(prefix)==int((plan.reuse_status=='reuse_after_prefix_check').sum())
    # Re-fetch one deterministic opening and touch sample in each period.
    sample=[];session=requests.Session()
    for year in ('2024','2026'):
      for cohort in ('opening','touch'):
        eligible=[obs for obs in allowed if str(candidates.loc[obs,'source_year'])==year and candidates.loc[obs,'cohort']==cohort]
        if not eligible:continue
        obs=sorted(eligible)[0];e=candidates.loc[obs];name=f'{e.contract}-1m-{e.day}.zip'
        url=f'https://data.binance.vision/data/futures/um/daily/klines/{e.contract}/1m/{name}'
        ch=session.get(url+'.CHECKSUM',timeout=(15,50));ch.raise_for_status();digest=ch.text.strip().split()[0].lower()
        r=session.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==digest==prefix[obs]['daily_sha256']
        daily=pd.read_csv(io.BytesIO(r.content),compression='zip').set_index('open_time')
        folder='breakout_2024_11' if year=='2024' else 'breakout_forward_2026'
        local=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{e.contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        times=range(int(e.quarter_start),int(e.trigger_minute)+M,M);cols=['open','high','low','close']
        a=local.reindex(times)[cols].to_numpy(float);b=daily.reindex(times)[cols].to_numpy(float)
        assert np.isfinite(a).all() and np.isfinite(b).all() and np.allclose(a,b,rtol=1e-9,atol=1e-12)
        sample.append({'observation_id':obs,'daily_sha256':digest})
        print('FIXED11_46_REUSE_SAMPLE',len(sample),flush=True)
    assert len(sample)==4
    out={'allowed_reuse_checked':len(allowed),'independent_daily_prefix_samples':len(sample),'samples':sample,
         'all_checks_pass':True,'note':'Exact pre-execution inputs; outcome-dependent source choices do not change signal eligibility.'}
    (H/'逐笔复用独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_REUSE_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
