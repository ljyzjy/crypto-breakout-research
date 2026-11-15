"""Reuse the independent event-level wallet audit for the raw 2022 scenarios."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import run_wallet as wallet

H=Path(__file__).resolve().parent;R85=H.parent/'第八十五轮_共享资金条件模拟';SCALAR=R85/'audit_wallet.py'


def load_records(_):
    return [{'period':r['period'],'obs':r['observation_id'],'lev':r['leverage'],'oi':True,'side':r['side'],
             'reference_ts':r['reference_ts'],'reference':Decimal(r['reference']),'stop':Decimal(r['stop']),
             'entry_ts':r['entry_ts'],'entry':Decimal(r['entry_fill']),'exit_ts':r['exit_ts'],
             'exit':Decimal(r['exit_fill']),'unit_net':Decimal(r['unit_net']),'funding':r['funding_events']}
            for r in wallet.load_records()]


def main():
    wallet.bulk.runner.guard(start=True); wallet.bulk.frozen()
    source=SCALAR.read_text(encoding='utf-8')
    old="""    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for key, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][key]
"""
    changes=[("sha(H / '冻结时点.json')","sha(H / '研究冻结.json')"),
             ("sha(H / 'wallet_simulator.py')","sha(R85 / 'wallet_simulator.py')"),
             ("sha(H / '钱包时序合成核验.json')","sha(R85 / '钱包时序合成核验.json')"),
             (old,"    frozen = {}\n"),
             ("len(result['rows']) == 40","len(result['rows']) == 4")]
    for a,b in changes:
        assert source.count(a)>=1,a
        source=source.replace(a,b)
    env={'__name__':'ext98_scalar_wallet','__file__':str(SCALAR)}
    exec(compile(source,str(SCALAR),'exec'),env);env.update({'H':H,'R85':R85,'load_inputs':load_records});env['main']()
    out_path=H/'共享钱包独立核验.json';out=json.loads(out_path.read_text(encoding='utf-8'))
    assert out['all_checks_pass'] and out['result_sha256']==wallet.bulk.sha(H/'共享钱包情景汇总.json')
    out.update(wrapper_code_sha256=wallet.bulk.sha(Path(__file__)),adapted_code_sha256=hashlib.sha256(source.encode()).hexdigest(),
               note='Cash and planned-risk scalar audit; unknown paths and floating equity remain excluded.')
    out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_WALLET_AUDIT',out['wallet_events_checked'],flush=True)


if __name__=='__main__':main()
