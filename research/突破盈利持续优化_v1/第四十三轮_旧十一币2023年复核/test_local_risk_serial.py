"""Synthetic checks for missing-day mark repair and conservative source conflicts."""
import hashlib,io,json,uuid,zipfile
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import settle_local_2023_serial as local
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;W=ROOT/'work'/'old11_2023_dual'/'risk_source_synthetic'/uuid.uuid4().hex;W.mkdir(parents=True,exist_ok=True)
def putzip(path,frame):
    path.parent.mkdir(parents=True,exist_ok=True);data=frame.to_csv(index=False).encode()
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('data.csv',data)
    return hashlib.sha256(path.read_bytes()).hexdigest()
class Response:
    def __init__(self,text):self.text=text
    def raise_for_status(self):pass
class Session:
    def __init__(self,checks):self.checks=checks
    def get(self,url,timeout=None):return Response(self.checks[url.split('/')[-1]])
def main():
    symbol='SYNTHUSDT';month='2023-02';day=int(pd.Timestamp('2023-02-24',tz='UTC').timestamp()*1000);prev=day-60_000
    mark=pd.DataFrame([{'open_time':prev,'open':100.,'high':101.,'low':99.,'close':100.}])
    daily=pd.DataFrame({'open_time':range(day,day+86_400_000,60_000),'open':100.,'high':101.,'low':99.,'close':100.})
    funding=pd.DataFrame([{'calc_time':int(pd.Timestamp('2023-02-01',tz='UTC').timestamp()*1000),'funding_interval_hours':8,'last_funding_rate':0.0001}])
    raw=W/'raw';repair=W/'repair';norm=W/'norm';cache=W/'cache';norm.mkdir(exist_ok=True);cache.mkdir(exist_ok=True)
    monthly=raw/'markPriceKlines'/symbol/f'{symbol}-1m-{month}.zip';monthly_sha=putzip(monthly,mark)
    dailyfile=repair/symbol/f'{symbol}-1m-2023-02-24.zip';daily_sha=putzip(dailyfile,daily)
    fundingfile=raw/'fundingRate'/symbol/f'{symbol}-fundingRate-{month}.zip';fund_sha=putzip(fundingfile,funding)
    pd.concat([mark,daily],ignore_index=True).rename(columns={'open_time':'ts'}).to_parquet(norm/f'{symbol}_markPriceKlines.parquet',index=False)
    funding.rename(columns={'calc_time':'ts'}).to_parquet(norm/f'{symbol}_fundingRate.parquet',index=False)
    local.RAW=raw;local.REPAIR=repair;local.NORM=norm;local.WORK=cache
    local.SOURCE={'records':[{'kind':'markPriceKlines','contract':symbol,'month':month,'status':'verified','sha256':monthly_sha},
                             {'kind':'fundingRate','contract':symbol,'month':month,'status':'verified','sha256':fund_sha}]}
    local.FIX={'records':[{'contract':symbol,'day':'2023-02-24','status':'verified_added','sha256':daily_sha}]}
    local.engine.session=lambda:Session({monthly.name+'.CHECKSUM':monthly_sha,dailyfile.name+'.CHECKSUM':daily_sha,fundingfile.name+'.CHECKSUM':fund_sha})
    local.psutil.virtual_memory=lambda:SimpleNamespace(available=8_000_000_000)
    local.engine.FINGERPRINT='synthetic_success';times=[prev,day+12*3_600_000]
    result=local.local_task(('markPriceKlines',symbol,month,times))
    assert result['status']=='verified' and result['repair']['sha256']==daily_sha and sorted(x['ts'] for x in result['rows'])==times
    fr=local.local_task(('fundingRate',symbol,month,[]));assert fr['status']=='verified' and len(fr['rows'])==1
    local.engine.FINGERPRINT='synthetic_bad_repair';local.FIX['records'][0]['sha256']='0'*64
    broken=local.local_task(('markPriceKlines',symbol,month,times));assert broken['status']=='error' and 'repair_hash_mismatch' in broken['error']
    local.FIX['records'][0]['sha256']=daily_sha;local.engine.FINGERPRINT='synthetic_bad_normalized'
    z=pd.read_parquet(norm/f'{symbol}_markPriceKlines.parquet');z.loc[z.ts.eq(times[1]),'close']=77.;z.to_parquet(norm/f'{symbol}_markPriceKlines.parquet',index=False)
    broken=local.local_task(('markPriceKlines',symbol,month,times));assert broken['status']=='error' and 'normalized_mark_value_disagreement' in broken['error']
    out={'verified_month_and_missing_day_repair':True,'verified_funding':True,
         'incorrect_repair_is_unknown':True,'normalized_source_disagreement_is_unknown':True,'all_checks_pass':True}
    (H/'本地风险来源串行合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_LOCAL_RISK_SYNTHETIC',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
