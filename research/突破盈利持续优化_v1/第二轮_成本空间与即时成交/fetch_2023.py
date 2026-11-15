"""Public 2023 archive download, reusing the checksum-verifying fetcher."""
import concurrent.futures
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent/'work'/'breakout_2023_11'
spec=importlib.util.spec_from_file_location('prior_archive_fetcher',HERE.parent/'fetch_2024.py')
fetcher=importlib.util.module_from_spec(spec);sys.modules[spec.name]=fetcher;spec.loader.exec_module(fetcher)
fetcher.ROOT=ROOT;fetcher.RAW=ROOT/'raw';fetcher.RAW.mkdir(parents=True,exist_ok=True)
def main():
    months=[f'2023-{m:02}' for m in range(1,13)];tasks=[]
    for c in fetcher.CONTRACTS:
        tasks += [('klines',c,m) for m in ['2022-12',*months]]
        tasks += [(kind,c,m) for kind in ['markPriceKlines','fundingRate'] for m in months]
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures=[executor.submit(fetcher.fetch,task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results)%40==0:print('2023_ARCHIVES',len(results),'/',len(tasks),flush=True)
    results.sort(key=lambda r:(r['kind'],r['contract'],r['month']))
    data={'expected':len(tasks),'verified':sum(x['status'] in ('verified','verified_cached') for x in results),
          'issues':[x for x in results if x['status'] not in ('verified','verified_cached')],
          'bytes':sum(x.get('bytes',0) for x in results),'records':results,
          'source':'https://github.com/binance/binance-public-data'}
    (HERE/'2023公开档案校验清单.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('2023_DOWNLOAD_COMPLETE',data['verified'],'/',data['expected'],'issues',len(data['issues']),
          'bytes',data['bytes'],'free',shutil.disk_usage(ROOT).free,flush=True)
if __name__=='__main__':main()
