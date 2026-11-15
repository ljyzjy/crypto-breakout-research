"""Deterministic microstructure edge cases for the hypothetical order simulator."""
import importlib.util,sys
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('maker_order_engine',HERE/'sim_order.py')
sim=importlib.util.module_from_spec(spec);sys.modules[spec.name]=sim;spec.loader.exec_module(sim)

class FakeMarket:
    def __init__(self,funding=None):self.funding={'S':funding or {}}
    def bar(self,c,t,mark=False):return np.array([100.,101.,99.,100.,1.,1e6])
    def funding_ok(self,c,t):return True

plan={'submit':0,'activate':1000,'expiry':180_000,'reference':100.,'planned_notional':100.,
      'planned_qty':1.,'side':1,'stop':99.,'atr':2.,'signal_close':100.,'contract':'S','observation_id':'x'}
def run(times,prices,qty,flags,q=0,target=1,method='limit',funding=None):
    return sim.run_order(plan,np.array(times,dtype='int64'),np.array(prices,float),np.array(qty,float),
                         np.array(flags,bool),method,target,q,FakeMarket(funding))

part=run([2000,3000],[100,101.1],[.4,1],[True,False])
assert part['status']=='filled' and abs(part['fill_fraction']-.4)<1e-12 and part['exit_reason']=='target'
wait=run([2000,180_001],[100,100],[9,1],[True,True],q=10)
assert wait['status']=='unfilled_expired'
through=run([2000],[98.5],[1],[True],q=100)
assert through['status']=='filled' and through['fill_fraction']==1 and through['exit_reason']=='stop' and through['net']<0
pre=run([1000,180_001],[100,100],[200,1],[True,True],q=0)
assert pre['status']=='unfilled_expired'
partial_queue=run([2000,3000],[100,101.1],[10.25,1],[True,False],q=10)
assert abs(partial_queue['fill_fraction']-.25)<1e-12
funded=run([2000,80_000],[100,101.1],[.4,1],[True,False],funding={60_000:[(60_000,.001)]})
assert abs(funded['funding_cost']-.04)<1e-12
shortplan=dict(plan,side=-1,stop=101.)
short=sim.run_order(shortplan,np.array([2000,3000]),np.array([100.,98.9]),np.array([.5,1.]),
                    np.array([False,True]),'limit',1,0,FakeMarket())
assert short['status']=='filled' and abs(short['fill_fraction']-.5)<1e-12 and short['exit_reason']=='target'
print('SIM_TESTS_PASS partial_fill queue_expiry gap_through_stop no_prefill queue_consumption funding short_side')
