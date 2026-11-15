"""Run the audited later-period risk engine over identical 1R entries."""
import hashlib,importlib.util,json,shutil,sys,time
from pathlib import Path
import psutil
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
spec=importlib.util.spec_from_file_location('risk48_later',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
WORK=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46';old_task=engine.task
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def guarded(z):
    while psutil.virtual_memory().available<500*1024**2:
        if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
        time.sleep(3)
    if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
    return old_task(z)
def main(year):
    f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(H/f'{year}冻结输入'/n)==v
    assert json.loads((H/'一倍止盈合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    out=H/f'{year}一倍止盈分批';names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
    hashes={n:sha(out/n) for n in names};(out/'风险输入哈希.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    WORK.mkdir(parents=True,exist_ok=True);engine.HERE=out;engine.WORK=WORK;engine.task=guarded
    print('EXIT1R48_LATER_RISK_BEGIN',year,flush=True);engine.main()
    for n,v in hashes.items():assert sha(out/n)==v
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
