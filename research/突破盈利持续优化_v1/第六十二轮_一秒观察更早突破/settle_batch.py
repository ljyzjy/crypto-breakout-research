"""Apply the existing audited funding/mark-price risk engine to the new paths."""
import importlib.util,json,shutil,sys,time
from pathlib import Path
import psutil
import run_observation as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
def main(year):
    runner.inputs(year);out=H/f'{year}一秒观察分批'
    quality=json.loads((out/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    if quality['variant_paths']==0:
        print('OBS62_RISK_NO_PATHS',year,flush=True);return
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    if year=='2023':
        old=P/'第四十三轮_旧十一币2023年复核';sys.path.insert(0,str(old));import settle_local_2023_serial as local
        assert json.loads((old/'本地风险来源串行合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
        frozen=json.loads((old/'风险来源冻结哈希.json').read_text(encoding='utf-8'));assert runner.sha(old/'冻结研究方案.md')==frozen['plan_sha256']
        for x in frozen['sources'].values():assert runner.sha(Path(x['path']))==x['sha256']
        copy=(old/'settle_2023_serial_engine.py').read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
        assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('OLD11_2023_RISK_COMPLETE'")]
        local.WORK.mkdir(parents=True,exist_ok=True);local.engine.HERE=out;local.engine.WORK=local.WORK;local.engine.task=local.local_task;engine=local.engine
    else:
        path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
        spec=importlib.util.spec_from_file_location('obs62risk',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
        copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
        assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
        old_task=engine.task;work=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46';work.mkdir(parents=True,exist_ok=True)
        def guarded(z):
            while psutil.virtual_memory().available<500*1024**2:
                if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
                time.sleep(3)
            if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
            return old_task(z)
        engine.HERE=out;engine.WORK=work;engine.task=guarded
    names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
    hashes={name:runner.sha(out/name) for name in names};(out/'风险输入哈希.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_RISK_BEGIN',year,flush=True);engine.main()
    for name,value in hashes.items():assert runner.sha(out/name)==value
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
