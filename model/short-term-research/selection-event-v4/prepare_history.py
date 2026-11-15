from types import FunctionType
import importlib.util
import event_engine as e

def main():
    spec=importlib.util.spec_from_file_location('causal_gate_v4',e.parent.ROOT/'build_gate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    scope=dict(module.discover.__globals__);scope['original']=e
    gates=FunctionType(module.discover.__code__,scope,argdefs=module.discover.__defaults__)(e.manifest())
    e.base.dump(e.ROOT/'quarantine.json',gates)
    for name in ('control','combined'):
        rows=e.parent.hourly_history(name)
        result=module.filter_rows(rows,gates,True)
        for old,new in zip(rows,result):
            byname={x['symbol']:x for x in old.get('excluded_data',[])+new['excluded_data']}
            new['excluded_data']=list(byname.values())
        e.base.dump(e.ROOT/'signals'/f'{name}-hourly.json.gz',result)
    print('Event candidate histories prepared; causal quarantine',gates,flush=True)

if __name__=='__main__':main()
