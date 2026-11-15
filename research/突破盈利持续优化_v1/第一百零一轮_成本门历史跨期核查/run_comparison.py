"""Apply the fixed cost gate to four previously audited aggregate-tape periods."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;R95=H.parent/'第九十五轮_扩充训练滚动预测';D=Decimal
sys.path.insert(0,str(R95));import run_expanded_walkforward as prior


def inputs():
    frozen=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in frozen['sources'].items():assert prior.sha(Path(path))==digest,path
    assert frozen['gate']==.004
    f77=json.loads((prior.R77/'冻结时点.json').read_text(encoding='utf-8'))
    datasets={};baseline={}
    for period in ('2023','2024','2026'):datasets[period],baseline[period]=prior.old.load(period,f77)
    datasets['2026_aug_oct']=prior.custom_load('2026_aug_oct')
    baseline['2026_aug_oct']=json.loads((prior.R81/'八至十月一秒观察结果.json').read_text(encoding='utf-8'))['rows']
    return datasets,baseline


def main():
    prior.guard.guard(start=True);data,baseline=inputs();results=[];details=[]
    for period,allrows in data.items():
      for lev in (10,20):
        variant=f'one_observation_2r_{lev}x';orig=[r for r in allrows if r['variant']==variant];selected=[]
        if period=='2026_aug_oct':
            ref=next(r for r in baseline[period] if r['leverage']==lev and r['exit_slippage_pct']==.05)
            unknown,expected=ref['unknown_candidates'],ref['known_trades']
        else:
            ref=next(r for r in baseline[period] if r['leverage']==lev)
            unknown,expected=ref['one_second_observation']['unknown'],ref['one_second_observation']['trades']
        assert len(orig)==expected
        for r in orig:
            s=r['signal'];side=int(s['side']);p=D(str(s['raw_entry_1s']));stop=D(str(s['stop_price']))
            assert side in (-1,1) and p>0 and int(s['entry_exec_ts'])>=int(s['decision_ts'])+1000 and r['entry_ts']>=int(s['entry_exec_ts'])+1000
            fraction=D(side)*(p-stop)/p;accept=fraction>=D('.004')
            if accept:selected.append(r)
            details.append({'period':period,'leverage':lev,'observation_id':r['observation_id'],'decision_ts':s['decision_ts'],
                            'reference_ts':s['entry_exec_ts'],'entry_ts':r['entry_ts'],'side':side,'reference':str(p),'stop':str(stop),
                            'fraction':str(fraction),'selected':accept,'net':r['net']})
        results.append({'period':period,'leverage':lev,'baseline':prior.old.stats(orig,unknown),'cost_gate':prior.old.stats(selected,unknown),
                        'rejected_known_trades':len(orig)-len(selected)})
    fields=list(details[0])
    with (H/'成本门逐笔明细.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(details)
    out={'rows':results,'detail_sha256':prior.sha(H/'成本门逐笔明细.csv'),'frozen_sha256':prior.sha(H/'研究冻结.json'),
         'code_sha256':prior.sha(Path(__file__)),'note':'Previously studied aggregate-tape periods; known unit paths only, original unknowns remain.'}
    (H/'成本门跨期结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT101_RESULTS',json.dumps(results,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
