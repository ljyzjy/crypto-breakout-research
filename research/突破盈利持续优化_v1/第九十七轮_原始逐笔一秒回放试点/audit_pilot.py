"""Independently parse and scalar-replay the three non-random raw-tape pilot cases."""
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import requests

H = Path(__file__).resolve().parent
P = H.parent
R90 = P/'第九十轮_二零二二公开行情'
R93 = P/'第九十三轮_原始逐笔抽样交叉核验'
sys.path.insert(0,str(R90)); import audit_tapes_2022, audit_risk_2022
sys.path.insert(0,str(R93)); import audit_raw_samples
sys.path.insert(0,str(P/'第六十二轮_一秒观察更早突破')); import audit_tape_samples
import run_pilot as pilot


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def close(x,y): return math.isclose(float(x),float(y),rel_tol=1e-9,abs_tol=1e-10)


def fresh_risk(source):
    kind, sym, month = source['kind'], source['contract'], source['month']
    name = f'{sym}-1m-{month}.zip' if kind=='markPriceKlines' else f'{sym}-fundingRate-{month}.zip'
    sub = f'{kind}/{sym}/1m/' if kind=='markPriceKlines' else f'{kind}/{sym}/'
    url = 'https://data.binance.vision/data/futures/um/monthly/' + sub + name
    ck = requests.get(url+'.CHECKSUM',timeout=(15,50)); ck.raise_for_status()
    fields = ck.text.strip().split(); assert len(fields)>=2 and fields[1]==name
    response=requests.get(url,timeout=(15,100)); response.raise_for_status(); body=response.content
    assert hashlib.sha256(body).hexdigest() == fields[0].lower() == source['sha256']
    frame=audit_risk_2022.independent_read(body,kind)
    return frame.apply(pd.to_numeric,errors='raise')


def audit_settlement(case, frames):
    total=0; sym=case['contract']; side=int(case['raw_result']['side'])
    for variant,path in case['raw_result'].get('paths',{}).items():
        if path['status']!='verified': continue
        saved=case['risk'][variant]
        if saved['risk_status']!='verified': continue
        start,end=int(path['entry_ts']),int(path['exit_ts']); entry=float(path['entry_fill']); exit=float(path['exit_fill'])
        qty=1/entry; funding=0.; extremes=[]
        for ts in range(start//60000*60000,end//60000*60000+60000,60000):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            marks=frames[('markPriceKlines',sym,month)]; row=marks[marks.open_time.eq(ts)]; assert len(row)==1
            m=row.iloc[0]; extremes.append(float(m['low' if side==1 else 'high']))
            fr=frames[('fundingRate',sym,month)].sort_values('calc_time'); assert len(fr)
            vals=fr[['calc_time','funding_interval_hours']].to_numpy(float)
            pos=np.searchsorted(vals[:,0],ts,side='right'); before=vals[max(0,pos-1)]; after=vals[min(len(vals)-1,pos)]
            allow=max(before[1],after[1])*3600000*1.5
            assert ((vals[0,0]-ts<=allow) if pos==0 else (ts-vals[-1,0]<=allow) if pos==len(vals) else (after[0]-before[0]<=allow))
            for f in fr.itertuples(index=False):
                ft=int(f.calc_time)
                if ft//60000*60000==ts and start<=ft<=end:
                    charge=side*qty*float(m['open'])*float(f.last_funding_rate)
                    funding += max(0.,charge) if ft in (start,end) else charge
        fee=.0005*qty*exit
        net=side*qty*(exit-entry)-.0005-fee-funding
        lev=int(variant.rsplit('_',1)[1].rstrip('x'))
        liq=any(1/lev-.0005-max(funding,0.)+side*qty*(x-entry)<=qty*x*.01 for x in extremes)
        assert close(saved['funding'],funding) and close(saved['entry_fee'],.0005) and close(saved['exit_fee'],fee)
        assert close(saved['net_per_unit_notional'],net) and close(saved['net_pct_notional'],100*net) and saved['liq_proxy']==liq
        total+=1
    return total


def main():
    pilot.runner.guard(start=True)
    path=H/'原始逐笔试点结果.json'; out=json.loads(path.read_text(encoding='utf-8'))
    assert out['code_sha256']==sha(H/'run_pilot.py') and out['plan_sha256']==sha(H/'研究冻结.json')
    found=pilot.get_inputs(); frames={}
    for source in out['risk_sources']:
        if source['status']=='verified':
            frames[(source['kind'],source['contract'],source['month'])]=fresh_risk(source)
    checked=[]
    for case in out['cases']:
        pilot.runner.guard(); e,cp,original=found[case['observation_id']]
        assert original==case['aggregate_result']
        body,meta=pilot.runner.minutes.archive('klines',e['contract'],e['day'])
        assert meta['sha256']==case['minute_archive']['sha256']
        bars=audit_tapes_2022.independent_bars(body,e['day'])
        lo,hi=int(e['trigger_minute']),int(e['quarter_end'])+60000
        rows=[]
        for archive in case['raw_archives']:
            p=pilot.runner.ROOT/'independent_raw_trade_samples'/f"{e['contract']}-trades-{archive['day']}.zip"
            assert sha(p)==archive['sha256']
            rows.extend(audit_raw_samples.independent_window(p,'trades',lo,hi))
        rows.sort(key=lambda r:(r[0],r[1]))
        tape=pd.DataFrame([(a,b,float(c),float(d),f) for a,b,c,d,f in rows],columns=['transact_time','agg_trade_id','price','quantity','is_buyer_maker'])
        assert len(tape)==case['raw_rows']
        status=case['raw_result']['status']
        if status=='minute_trade_ohlc_mismatch':
            first=tape[(tape.transact_time>=lo)&(tape.transact_time<lo+60000)]; bar=bars.loc[lo]
            actual=[first.price.iloc[0],first.price.max(),first.price.min(),first.price.iloc[-1]]
            assert not all(close(a,bar[k]) for a,k in zip(actual,('open','high','low','close')))
            paths=0
        else:
            assert status in ('qualified','flow_filter_not_met','known_risk_rejected','first_direction_ineligible','no_order_time')
            paths=audit_tape_samples.replay(e,tape,bars,case['raw_result'])
        settled=audit_settlement(case,frames) if 'side' in case['raw_result'] else 0
        checked.append({'observation_id':case['observation_id'],'status':status,'paths_checked':paths,'settlements_checked':settled})
        print('EXT97_AUDIT',len(checked),'/',len(out['cases']),flush=True)
    result={'all_checks_pass':True,'cases':checked,'source_sha256':sha(path),'code_sha256':sha(Path(__file__)),
            'independently_redownloaded_risk_archives':len(frames),
            'note':'Independent chunk parser, scalar path checks, fresh risk archive SHA and independent settlement arithmetic; sample is non-random.'}
    (H/'原始逐笔试点独立核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT97_AUDIT_PASS',len(checked),sum(c['settlements_checked'] for c in checked),flush=True)


if __name__=='__main__':main()
