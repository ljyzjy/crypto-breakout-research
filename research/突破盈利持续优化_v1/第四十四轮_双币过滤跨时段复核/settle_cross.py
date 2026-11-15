"""Sequentially recover historical mark/funding archives for the frozen batches."""
import hashlib, json, shutil, time
from pathlib import Path
import psutil
import settle_cross_engine as engine
H=Path(__file__).resolve().parent
ROOT=H.parent.parent.parent
WORK=ROOT/'work'/'point_in_time_universe33'/'risk_cross44'
orig_task=engine.task
def guarded_task(spec):
    # Only one small monthly risk archive is read at a time; preserve disk headroom.
    while psutil.virtual_memory().available < 700*1024**2:
        time.sleep(3)
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            return {'kind':spec[0],'contract':spec[1],'month':spec[2],'status':'error','error':'disk_headroom','rows':[]}
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        return {'kind':spec[0],'contract':spec[1],'month':spec[2],'status':'error','error':'disk_headroom','rows':[]}
    return orig_task(spec)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    original=(H.parent/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=(H/'settle_cross_engine.py').read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    plan=sha(H/'冻结研究方案.md');frozen=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert plan==frozen['plan_sha256']
    q=json.loads((H/'事前市场过滤质量.json').read_text(encoding='utf-8'))
    assert sha(H/'候选事前市场过滤.parquet')==q['decision_sha256']
    assert json.loads((H/'事前市场过滤时序核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    WORK.mkdir(parents=True,exist_ok=True);engine.WORK=WORK;engine.task=guarded_task
    for period in ('2024_may_jun','2026_may_jul'):
        out=H/period; b=json.loads((out/'风险批次冻结哈希.json').read_text(encoding='utf-8'))
        assert b['research_plan_sha256']==plan and b['decision_sha256']==q['decision_sha256']
        for n in ('动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json'):
            assert sha(out/n)==b[n]
        print('CROSS44_PERIOD_BEGIN',period,flush=True);engine.HERE=out;engine.main()
if __name__=='__main__':main()
