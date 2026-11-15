"""Preserve the audited 44-replayed-candidate interim snapshot."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;B=H/'2024一秒入场分批';OUT=H/'2024中间批次_44候选';OUT.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    audit=json.loads((H/'2024一秒入场账本独立核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass'] and audit['audited_one_second_paths']==83
    quality=json.loads((B/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    assert quality['event_statuses'].get('qualified')==44 and quality['event_statuses'].get('archive_pending')==3
    risk=json.loads((B/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
    assert risk['risk_statuses'].get('verified')==83 and risk['risk_statuses'].get('missing_mark_minute')==4
    sources={n:B/n for n in ['动态池逐笔信号筛查.parquet','动态池延迟市价路径.parquet','动态池逐笔提取质量.json','逐笔执行冻结方案.json',
                              '动态池单位收益与风险.parquet','动态池单位筛查完整性.json','动态池风险档案核验清单.json','风险输入哈希.json']}
    for n in ('2024一秒五秒配对对照.json','2024一秒五秒逐笔配对结果.parquet','2024一秒入场逐笔独立抽查.json','2024一秒入场账本独立核验.json'):
        sources[n]=H/n
    for name,src in sources.items():
        dst=OUT/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    z={'all_checks_pass':True,'files':{n:sha(OUT/n) for n in sources},
       'note':'Incomplete snapshot; 44 replayed, 3 pending, 2 pairs have missing cached mark minutes; original unknowns remain.'}
    (OUT/'中间快照哈希.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_2024_INTERIM_V2_FROZEN',len(sources),flush=True)
if __name__=='__main__':main()
