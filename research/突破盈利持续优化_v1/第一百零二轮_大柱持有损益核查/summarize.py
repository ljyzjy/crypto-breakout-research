"""Group paired, verified time-stop outcomes by ex-post candle body label."""
import csv
import json
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R100=P/'第一百轮_突破无进展提前退出'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True)
    audit=json.loads((H/'大柱标签独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['labels_sha256']==bulk.sha(H/'事后大柱标签.parquet')
    p=json.loads((R100/'进展退出独立核验.json').read_text(encoding='utf-8'))
    assert p['all_checks_pass'] and p['ledger_sha256']==bulk.sha(R100/'进展退出单位账本.parquet')
    labels=pd.read_parquet(H/'事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    new=pd.read_parquet(R100/'进展退出单位账本.parquet');old=pd.read_parquet(R98/'原始逐笔批次/单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    rows=[]
    for r in new.to_dict('records'):
        if r['risk_status']!='verified' or bool(r['liq_proxy']):continue
        obs=r['observation_id'];label=labels[obs];orig=old[(obs,r['variant'])]
        assert int(label['side'])==int(r['side']) and int(orig['entry_ts'])==int(r['entry_ts'])
        group='unknown' if label['status']!='verified' else 'large_aligned' if bool(label['large_aligned']) else 'other'
        a=float(orig['net_per_unit_notional']);b=float(r['net_per_unit_notional'])
        rows.append({'observation_id':obs,'leverage':int(r['variant'].rsplit('_',1)[1].rstrip('x')),
                     'label_status':label['status'],'label':group,'action':r['time_stop_action'],
                     'original_net':a,'time_stop_net':b,'difference':b-a})
    with (H/'大柱对照逐笔.csv').open('w',encoding='utf-8',newline='') as f:
        fields=['observation_id','leverage','label_status','label','action','original_net','time_stop_net','difference']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary=[]
    for lev in (10,20):
      for label in ('large_aligned','other','unknown'):
        subset=[r for r in rows if r['leverage']==lev and r['label']==label];n=len(subset)
        summary.append({'leverage':lev,'label':label,'trades':n,'early_exits':sum(r['action']=='early_exit' for r in subset),
                        'original_net_wins':sum(r['original_net']>0 for r in subset),'time_stop_net_wins':sum(r['time_stop_net']>0 for r in subset),
                        'original_mean_pct_notional':100*sum(r['original_net'] for r in subset)/n if n else None,
                        'time_stop_mean_pct_notional':100*sum(r['time_stop_net'] for r in subset)/n if n else None,
                        'better':sum(r['difference']>1e-12 for r in subset),'worse':sum(r['difference']< -1e-12 for r in subset),
                        'unchanged':sum(abs(r['difference'])<=1e-12 for r in subset)})
    out={'rows':summary,'detail_sha256':bulk.sha(H/'大柱对照逐笔.csv'),'label_audit_sha256':bulk.sha(H/'大柱标签独立核验.json'),
         'path_audit_sha256':bulk.sha(R100/'进展退出独立核验.json'),'code_sha256':bulk.sha(Path(__file__)),
         'note':'Ex-post labels among entered verified opportunities only, not market-wide capture rates or realtime signals.'}
    (H/'大柱退出对照结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('EXT102_RESULTS',json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
