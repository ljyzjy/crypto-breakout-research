"""Verify official day archives and fixed-pool minute prefixes before tape reuse."""
import hashlib,io,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil,requests
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'逐笔冻结输入';M=60_000
WORK=ROOT/'work'/'fixed11_cross46'/'reuse';WORK.mkdir(parents=True,exist_ok=True)
PLAN=H/'逐笔复用计划.parquet';META=H/'逐笔复用计划质量.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
FP=hashlib.sha256(Path(__file__).read_bytes()+(H/'逐笔输入冻结哈希.json').read_bytes()+PLAN.read_bytes()).hexdigest()
def main():
    info=json.loads(META.read_text(encoding='utf-8'));assert sha(PLAN)==info['plan_sha256']
    candidates=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True)
    plan=pd.read_parquet(PLAN);need=set(plan.loc[plan.reuse_status.eq('reuse_after_prefix_check'),'observation_id'])
    candidates=candidates[candidates.observation_id.isin(need)];old=pd.concat([pd.read_parquet(I/'old_signal.parquet'),pd.read_parquet(I/'backup_signal.parquet')],ignore_index=True).set_index('observation_id')
    archive={}
    for root in (ROOT/'work'/'point_in_time_universe33'/'tape',ROOT/'work'/'point_in_time_universe34'/'tape'):
        for file in sorted(root.glob('*.json')):
            z=json.loads(file.read_text(encoding='utf-8'))
            if z.get('status')!='verified':continue
            matches=[r for r in z['rows'] if r['observation_id'] in need]
            if not matches:continue
            k=next((a for a in z['archives'] if a['kind']=='klines' and a['day']==z['day']),None)
            if k is None:continue
            for row in matches:
                obs=row['observation_id'];assert row['status']==old.loc[obs,'status']
                val={'daily_sha256':k['sha256'],'checkpoint':str(file),'archives':z['archives']}
                if obs in archive:assert archive[obs]['daily_sha256']==val['daily_sha256']
                archive[obs]=val
    session=requests.Session();errors=[];done=0
    for (sym,day),group in candidates.groupby(['contract','day'],sort=True):
        ids=sorted(group.observation_id);key=hashlib.sha256((FP+'|'+sym+'|'+day+'|'+'|'.join(ids)).encode()).hexdigest();file=WORK/(key+'.json')
        if file.exists():
            rec=json.loads(file.read_text(encoding='utf-8'));assert rec['status']=='verified';done+=1;continue
        while psutil.virtual_memory().available<350*1024**2:
            if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
            time.sleep(3)
        try:
            if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
            name=f'{sym}-1m-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{name}'
            c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();expected=c.text.strip().split()[0].lower()
            res=session.get(url,timeout=(15,90));res.raise_for_status();assert hashlib.sha256(res.content).hexdigest()==expected
            d=pd.read_csv(io.BytesIO(res.content),compression='zip');assert {'open_time','open','high','low','close'}.issubset(d.columns)
            d=d[['open_time','open','high','low','close']].apply(pd.to_numeric,errors='raise').set_index('open_time');assert d.index.is_unique
            year=int(day[:4]);folder='breakout_2024_11' if year==2024 else 'breakout_forward_2026'
            norm=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{sym}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
            rows=[]
            for e in group.to_dict('records'):
                obs=e['observation_id'];a=archive.get(obs)
                status='verified'
                if a is None:status='old_archive_provenance_missing'
                elif a['daily_sha256']!=expected:status='official_day_source_changed'
                else:
                    idx=range(int(e['quarter_start']),int(e['trigger_minute'])+M,M);x=norm.reindex(idx);y=d.reindex(idx)
                    cols=['open','high','low','close']
                    if not np.isfinite(x[cols].to_numpy(float)).all() or not np.isfinite(y[cols].to_numpy(float)).all() or not np.allclose(x[cols],y[cols],rtol=1e-9,atol=1e-12):status='daily_monthly_ohlc_mismatch'
                rows.append({'observation_id':obs,'status':status,'old_checkpoint':a['checkpoint'] if a else None})
            rec={'status':'verified','contract':sym,'day':day,'daily_sha256':expected,'rows':rows}
            temp=file.with_suffix('.partial');temp.write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(file)
        except Exception as exc:
            errors.append({'contract':sym,'day':day,'error':type(exc).__name__+':'+str(exc)[:150]})
        done+=1
        if done%10==0:print('FIXED11_46_REUSE_PREFIX',done,'groups','errors',len(errors),flush=True)
    out={'planned_reuse_events':len(need),'verified_groups':len(list(WORK.glob('*.json'))),'errors':errors,'fingerprint':FP,
         'note':'Only matching daily SHA and OHLC prefix authorize reuse; other records remain unknown.'}
    (H/'逐笔复用前缀进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_REUSE_PREFIX_DONE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
