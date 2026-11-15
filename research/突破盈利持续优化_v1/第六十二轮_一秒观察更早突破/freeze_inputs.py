"""Freeze all prior fixed-pool candidates and first-breakout evidence."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;R47=P/'第四十七轮_一次重新突破确认';R46=P/'第四十六轮_固定十一加密币跨时段';R43=P/'第四十三轮_旧十一币2023年复核'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    test=json.loads((H/'一秒观察合成时序核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(H/'one_second_observation.py') and test['plan_sha256']==sha(H/'冻结研究方案.md')
    for year in ('2023','2024','2026'):
        dest=H/f'{year}冻结输入';manifest=H/f'{year}输入冻结哈希.json';assert not dest.exists() and not manifest.exists()
        i=R47/('2023冻结输入' if year=='2023' else '跨期冻结输入')
        meta=json.loads((R47/('2023输入冻结哈希.json' if year=='2023' else '跨期输入冻结哈希.json')).read_text(encoding='utf-8'))
        assert sha(R47/'冻结研究方案.md')==meta['plan_sha256'] and all(sha(i/n)==v for n,v in meta['inputs'].items())
        if year=='2023':
            source={'candidates.parquet':i/'candidates.parquet','baseline_signal.parquet':i/'baseline_signal.parquet',
                    'baseline_paths.parquet':i/'baseline_paths.parquet','baseline_ledger.parquet':i/'baseline_ledger.parquet',
                    'baseline_quality.json':i/'baseline_quality.json','baseline_audit.json':i/'baseline_audit.json',
                    'minute_sources.json':i/'minute_sources.json','execution.json':R43/'部分批次'/'逐笔执行冻结方案.json'}
        else:
            fixed=json.loads((R46/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'))
            candidate=R46/'逐笔冻结输入'/f'{year}_candidates.parquet';execution=R46/'逐笔冻结输入'/'old_execution_plan.json'
            assert sha(candidate)==fixed['inputs'][f'{year}_candidates.parquet'] and sha(execution)==fixed['inputs']['old_execution_plan.json']
            source={'candidates.parquet':candidate,'baseline_signal.parquet':i/f'{year}_signal.parquet',
                    'baseline_paths.parquet':i/f'{year}_paths.parquet','baseline_ledger.parquet':i/f'{year}_ledger.parquet',
                    'baseline_quality.json':i/f'{year}_quality.json','baseline_audit.json':i/'baseline_audit.json',
                    'minute_sources.json':i/'minute_sources.json','provenance.json':i/'provenance.json','execution.json':execution}
        source['baseline_summary.json']=R47/'单次重试跨期单位对照.json'
        dest.mkdir()
        for name,path in source.items():shutil.copy2(path,dest/name);assert sha(dest/name)==sha(path)
        cand=pd.read_parquet(dest/'candidates.parquet');signals=pd.read_parquet(dest/'baseline_signal.parquet')
        assert cand.observation_id.is_unique and signals.observation_id.is_unique and set(cand.observation_id)==set(signals.observation_id)
        assert len(cand)=={'2023':146,'2024':119,'2026':39}[year]
        z={'year':year,'plan_sha256':sha(H/'冻结研究方案.md'),'decision_code_sha256':sha(H/'one_second_observation.py'),
           'input_sha256':{name:sha(dest/name) for name in source},'source_paths':{name:str(path) for name,path in source.items()},
           'note':'All candidate events preserved; original unknowns stay unknown. No post-close labels included in the signal inputs.'}
        manifest.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
        print('OBS62_FROZEN',year,'candidates',len(cand),'known_statuses',signals.status.value_counts().to_dict(),flush=True)
if __name__=='__main__':main()
