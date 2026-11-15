"""Sequential official mark/funding risk settlement for the fixed-11 batches."""
import hashlib,importlib.util,json,shutil,sys,time
from pathlib import Path
import psutil
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'逐笔冻结输入'
path=P/'第四十四轮_双币过滤跨时段复核'/'settle_cross_engine.py'
spec=importlib.util.spec_from_file_location('fixed11_risk46',path);engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
WORK=ROOT/'work'/'point_in_time_universe33'/'risk_fixed11_cross46';original_task=engine.task
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def guarded(z):
    while psutil.virtual_memory().available<500*1024**2:
        if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
        time.sleep(3)
    if shutil.disk_usage(ROOT).free<2_200_000_000:return {'kind':z[0],'contract':z[1],'month':z[2],'status':'error','error':'disk_headroom','rows':[]}
    return original_task(z)
def main():
    f=json.loads((H/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    assert json.loads((H/'逐笔复用独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    assert json.loads((H/'新逐笔读取一致性核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=path.read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    WORK.mkdir(parents=True,exist_ok=True);engine.WORK=WORK;engine.task=guarded
    for year in ('2024','2026'):
        out=H/year/'逐笔分批';names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
        hashes={n:sha(out/n) for n in names};(out/'风险输入哈希.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
        print('FIXED11_46_RISK_BEGIN',year,flush=True);engine.HERE=out;engine.main()
        for n,v in hashes.items():assert sha(out/n)==v
if __name__=='__main__':main()
