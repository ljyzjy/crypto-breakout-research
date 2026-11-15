"""Independently verify all available 15-minute labels against official daily files."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import requests

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk
sys.path.insert(0,str(bulk.R90));from audit_tapes_2022 import independent_bars


def main():
    bulk.runner.guard(start=True);quality=json.loads((H/'大柱标签质量.json').read_text(encoding='utf-8'))
    assert quality['code_sha256']==bulk.sha(H/'prepare_labels.py') and quality['label_sha256']==bulk.sha(H/'事后大柱标签.parquet')
    labels=pd.read_parquet(H/'事后大柱标签.parquet');signals=pd.read_parquet(R98/'原始逐笔批次/逐笔信号.parquet').set_index('observation_id').to_dict('index')
    assert labels.observation_id.is_unique and len(labels)==quality['label_count']
    sources=json.loads((bulk.R90/'二零二二日档补源质量.json').read_text(encoding='utf-8'))['selected_sources']
    bysymbol={x['symbol']:x for x in sources};arcs={(x['contract'],x['day']):x for x in quality['archives']};checked=0;unknown=0
    for sym,g in labels.groupby('contract',sort=True):
        source=bysymbol[sym];assert bulk.sha(source['path'])==source['sha256']
        norm=pd.read_parquet(source['path'],columns=['ts','open','high','low','close','volume','quote_volume','trade_count']).set_index('ts')
        for day,part in g.groupby('day',sort=True):
            bulk.runner.guard();a=arcs.get((sym,day));daily=None
            if a:
                p=Path(a['path']);assert bulk.sha(p)==a['sha256']
                name=p.name;url=f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{name}.CHECKSUM'
                response=requests.get(url,timeout=(15,50));response.raise_for_status();fields=response.text.strip().split()
                assert fields[0].lower()==a['sha256'] and Path(fields[1]).name==name
                daily=independent_bars(p.read_bytes(),day)
            for r in part.to_dict('records'):
                s=signals[r['observation_id']];q=int(s['quarter_start']);side=int(s['side']);atr=D(str(s['atr']))
                assert q==int(r['quarter_start']) and side==int(r['side']) and atr==D(str(r['atr']))
                times=list(range(q,q+15*60000,60000));b=norm.reindex(times)
                v=b[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
                valid=len(b)==15 and np.isfinite(v).all() and (v>0).all() and atr>0
                if not valid:assert r['status']=='unknown_invalid_normalized';unknown+=1;checked+=1;continue
                if daily is None:assert r['status']=='unknown_daily_source';unknown+=1;checked+=1;continue
                official=daily.reindex(times)[['open','high','low','close']].to_numpy(float);local=b[['open','high','low','close']].to_numpy(float)
                agrees=np.isfinite(official).all() and np.allclose(local,official,rtol=1e-9,atol=1e-12)
                if not agrees:assert r['status']=='unknown_daily_ohlc_mismatch';unknown+=1;checked+=1;continue
                assert r['status']=='verified';o=D(str(b.open.iloc[0]));c=D(str(b.close.iloc[-1]))
                assert D(str(r['quarter_open']))==o and D(str(r['quarter_close']))==c and bool(r['large_aligned'])==(D(side)*(c-o)>=atr)
                checked+=1
            print('EXT102_AUDIT_LABEL',checked,'/',len(labels),sym,day,flush=True)
    assert checked==len(labels)
    out={'all_checks_pass':True,'labels_checked':checked,'unknown_labels':unknown,'source_archives_checked':len(arcs),
         'source_sha256':bulk.sha(H/'大柱标签质量.json'),'labels_sha256':bulk.sha(H/'事后大柱标签.parquet'),
         'code_sha256':bulk.sha(Path(__file__)),'note':'Independent daily CSV parser and official ZIP CHECKSUM; missing and mismatched bars remain unknown.'}
    (H/'大柱标签独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT102_LABEL_AUDIT',checked,unknown,flush=True)


if __name__=='__main__':main()
