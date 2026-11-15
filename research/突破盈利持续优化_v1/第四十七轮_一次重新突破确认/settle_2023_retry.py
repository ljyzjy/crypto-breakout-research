"""Apply the already-audited 2023 risk source and cost formulas to retry paths."""
import hashlib,json,sys
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;OLD=P/'第四十三轮_旧十一币2023年复核';OUT=H/'2023重试分批'
sys.path.insert(0,str(OLD));import settle_local_2023_serial as local
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'2023输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(H/'2023冻结输入'/n)==v
    assert json.loads((OLD/'本地风险来源串行合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    frozen=json.loads((OLD/'风险来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(OLD/'冻结研究方案.md')==frozen['plan_sha256']
    for x in frozen['sources'].values():assert sha(Path(x['path']))==x['sha256']
    original=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy=(OLD/'settle_2023_serial_engine.py').read_text(encoding='utf-8').replace('max_workers=1','max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('OLD11_2023_RISK_COMPLETE'")]
    names=['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json']
    snapshot={n:sha(OUT/n) for n in names};(OUT/'风险输入哈希.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    local.WORK.mkdir(parents=True,exist_ok=True);local.engine.HERE=OUT;local.engine.WORK=local.WORK;local.engine.task=local.local_task
    print('RETEST47_2023_RISK_BEGIN',flush=True);local.engine.main()
    for n,v in snapshot.items():assert sha(OUT/n)==v
if __name__=='__main__':main()
