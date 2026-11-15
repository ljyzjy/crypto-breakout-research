"""Check overlapping completed dynamic events against the earlier verified tape paths."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
WORK=ROOT/'work'/'point_in_time_universe33'/'tape'
def main():
    old=pd.read_parquet(PARENT/'第二十八轮_原十八币池扩展'/'十八币首次触价五秒成交.parquet')
    old=old[old.status.eq('verified')].copy();old['base_id']=old.observation_id.str.rsplit('|',n=1).str[0]
    assert old.base_id.is_unique;lookup=old.set_index('base_id')
    paths=pd.read_parquet(PARENT/'第二十九轮_秒级延迟与失败退出'/'秒级路径与延迟参考.parquet')
    paths=paths[paths.variant.isin(['normal_2r','fast_2r'])].set_index(['observation_id','variant'])
    counts={'checkpoint_tasks':0,'overlap_signals':0,'compared_previous_20x_paths':0};maxerr=0.;seen=set()
    for file in sorted(WORK.glob('*.json')):
        record=json.loads(file.read_text(encoding='utf-8'));counts['checkpoint_tasks']+=1
        if record.get('status')!='verified':continue
        agg=next(a for a in record['archives'] if a['kind']=='aggTrades' and a['day']==record['day'])
        for row in record['rows']:
            if row.get('status') not in ('qualified','flow_filter_not_met','known_risk_rejected') or row['observation_id'] not in lookup.index or row['observation_id'] in seen:continue
            seen.add(row['observation_id'])
            z=lookup.loc[row['observation_id']]
            if int(row['side'])!=int(z.side):raise ValueError('first direction mismatch')
            assert z.archive_sha256==agg['sha256']
            for field in ('decision_ts','entry_exec_ts','five_count'):
                assert int(row[field])==int(z[field]),(row['observation_id'],field)
            for field in ('signal_close','raw_entry_5s','buy_notional','sell_notional'):
                a=float(row[field]);b=float(z[field]);err=abs(a-b)/max(1.,abs(b));maxerr=max(maxerr,err)
                assert np.isclose(a,b,rtol=1e-10,atol=1e-8),(row['observation_id'],field)
            if row['five_imbalance'] is not None and pd.notna(z.five_imbalance):
                assert np.isclose(float(row['five_imbalance']),float(z.five_imbalance),rtol=1e-10,atol=1e-12)
            counts['overlap_signals']+=1
            for v in ('normal_2r','fast_2r'):
                key=v+'_20x';oldkey=(z.observation_id,v)
                if key not in row.get('paths',{}) or oldkey not in paths.index:continue
                new=row['paths'][key];prior=paths.loc[oldkey];assert new['status']==prior.status
                if new['status']=='verified':
                    for k in ('entry_ts','exit_signal_ts','exit_ts','reason'):assert new[k]==prior[k],(row['observation_id'],k)
                    for k in ('entry_raw','entry_fill','exit_raw','exit_fill'):assert np.isclose(new[k],prior[k],rtol=1e-11,atol=1e-12)
                counts['compared_previous_20x_paths']+=1
    counts['max_relative_signal_error']=maxerr
    counts['note']='Completed checkpoints only; agreement does not validate new symbols, exchange fills or performance.'
    (HERE/'旧币逐笔信号重合核验.json').write_text(json.dumps(counts,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_OVERLAP_AUDIT',json.dumps(counts,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
