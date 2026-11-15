"""Freeze the equivalent low-memory implementation and its parity evidence."""
import hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    old=json.loads((H/'来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md')==old['plan_sha256']
    assert json.loads((H/'小块算法一致性核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    for group in ('sources','code','support'):
        for item in old[group].values():assert sha(Path(item['path']))==item['sha256']
    code=dict(old['code']);code['prepare']={'path':str(H/'prepare_fixed11_chunked.py'),'sha256':sha(H/'prepare_fixed11_chunked.py')}
    for name,file in [('chunk_engine','chunk_exact.py'),('chunk_feature','minute_features_chunked.py'),
                      ('chunk_test','test_chunk_parity.py'),('chunk_test_result','小块算法一致性核验.json')]:
        p=H/file;code[name]={'path':str(p),'sha256':sha(p)}
    out={'plan_sha256':old['plan_sha256'],'sources':old['sources'],'code':code,'support':old['support'],
         'note':'Same source periods and rules; small-block implementation passed two full-array parity samples.'}
    target=H/'小块来源冻结哈希.json'
    if target.exists():assert json.loads(target.read_text(encoding='utf-8'))==out
    else:target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_CHUNK_SOURCES_FROZEN',len(out['sources']),len(code),flush=True)
if __name__=='__main__':main()
