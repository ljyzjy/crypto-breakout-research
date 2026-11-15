from common import ROOT,SOURCE,read,dump,sha
import subprocess,sys,datetime
files=['protocol.json','features.py','engine.py','guard.py','common.py','validate_rules.py','signals.parquet','hourly-ranks.parquet','hourly.parquet','regimes.parquet']
if __name__=='__main__':
    assert read(ROOT/'registration.json')['protocol_sha256']==sha(ROOT/'protocol.json')
    subprocess.run([sys.executable,str(ROOT/'validate_rules.py')],check=True)
    if not (ROOT/'frozen.json').exists():
        assert not (ROOT/'metrics.json').exists()
        dump(ROOT/'frozen.json',{'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hashes':{x:sha(ROOT/x) for x in files},'results_seen':False,'parameter_search':False,'previous_strategy_frozen_sha':sha(SOURCE/'frozen.json')})
    assert all(sha(ROOT/x)==h for x,h in read(ROOT/'frozen.json')['hashes'].items())
    subprocess.run([sys.executable,str(ROOT/'engine.py')],check=True)
