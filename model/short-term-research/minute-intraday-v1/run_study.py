from pathlib import Path
import subprocess,sys
import pandas as pd
from prepare_data import ROOT,read,dump,sha

def main():
    assert (ROOT/'data-manifest.json').exists(),'Finish minute archive acquisition first'
    assert read(ROOT/'registration.json')['protocol_sha256']==sha(ROOT/'protocol.json')
    subprocess.run([sys.executable,str(ROOT/'test_minute.py')],check=True)
    if not (ROOT/'feature-manifest.json').exists():
        subprocess.run([sys.executable,str(ROOT/'features.py')],check=True)
    if not (ROOT/'frozen.json').exists():
        assert not (ROOT/'metrics.json').exists()
        files=['protocol.json','data-plan.json','data-manifest.json','feature-manifest.json',
               'features.py','engine.py','test_minute.py','analyze.py']
        dump(ROOT/'frozen.json',{'utc':pd.Timestamp.now(tz='UTC').isoformat(),
             'hashes':{n:sha(ROOT/n) for n in files},'results_seen':False,'parameter_search':False})
    frozen=read(ROOT/'frozen.json')
    assert all(sha(ROOT/n)==h for n,h in frozen['hashes'].items()),'Frozen study changed; create an explicit new research version instead'
    subprocess.run([sys.executable,str(ROOT/'engine.py')],check=True)
    subprocess.run([sys.executable,str(ROOT/'analyze.py')],check=True)

if __name__=='__main__':main()
