import json,unittest
import numpy as np
import pandas as pd
import engine
from study import P,metric

MODES=P['main_variants']+P['diagnostic_variants']

class CausalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index=pd.date_range('2022-01-01','2023-12-31',tz='UTC');rng=np.random.default_rng(17);cls.data={}
        for i,s in enumerate(['BTCUSDT','ETHUSDT','AUSDT','BUSDT','CUSDT','DUSDT','EUSDT','FUSDT']):
            c=100*np.exp(np.cumsum(rng.normal(.001,.025,len(index))))
            cls.data[s]=pd.DataFrame({'open':c,'high':c*1.025,'low':c*.975,'close':c,'volume':1e6,'quote_volume':2e7+i*1e6},index=index)

    def test_all_variants_prefix_perturbations_and_accounting(self):
        cut='2023-08-28'
        for mode in MODES:
            with self.subTest(mode=mode):
                full=engine.simulate(self.data,'2023-01-01','2023-12-31',mode=mode)
                short=engine.simulate({s:d.loc[:cut] for s,d in self.data.items()},'2023-01-01',cut,mode=mode)
                assert [t for t in full['trace'] if t['date']<=cut]==short['trace']
                assert [o for o in full['orders'] if o['date']<=cut]==[o for o in short['orders'] if o['reason']!='window_end']
                changed={s:d.copy() for s,d in self.data.items()}
                for d in changed.values():d.loc[cut:,['open','high','low','close','quote_volume']]*=100
                mutant=engine.simulate(changed,'2023-01-01',cut,mode=mode)
                assert short['trace']==mutant['trace']
                for t in full['trace']:
                    assert t['information_through']<t['date']
                    assert sum(t['weights'].values())<=.20000001
                    assert len(t['weights'])<=4
                    assert all(0<=v<=.10000001 for v in t['weights'].values())
                metric(full)

    def test_formation_boundary(self):
        with self.assertRaises(ValueError):engine.simulate(self.data,'2022-12-01','2023-01-31')

def real_validation():
    data=engine.load();checks=[]
    for mode in MODES:
        full=engine.simulate(data,'2023-01-01','2026-10-31',mode=mode)
        for cut in ['2023-06-30','2024-06-30','2025-06-30']:
            short=engine.simulate({s:d.loc[:cut] for s,d in data.items()},'2023-01-01',cut,mode=mode)
            assert [t for t in full['trace'] if t['date']<=cut]==short['trace'],(mode,cut,'decisions')
            assert [o for o in full['orders'] if o['date']<=cut]==[o for o in short['orders'] if o['reason']!='window_end'],(mode,cut,'orders')
        changed={s:d.copy() for s,d in data.items()}
        for d in changed.values():d.loc['2025-01-01':,['open','high','low','close','quote_volume']]*=100
        mutant=engine.simulate(changed,'2023-01-01','2026-10-31',mode=mode)
        assert [t for t in full['trace'] if t['date']<='2025-01-01']==[t for t in mutant['trace'] if t['date']<='2025-01-01']
        metric(full);checks.append({'mode':mode,'three_prefixes_and_future_mutation':'PASS','cash_ledger':'PASS'})
        print('real causal checks PASS',mode,flush=True)
    from study import ROOT,fingerprint
    assert fingerprint()==json.loads((ROOT/'frozen.json').read_text())['hashes']
    (ROOT/'causality.json').write_text(json.dumps(checks,indent=2))

if __name__=='__main__':
    import sys
    if '--real' in sys.argv:real_validation()
    else:unittest.main(verbosity=2)
