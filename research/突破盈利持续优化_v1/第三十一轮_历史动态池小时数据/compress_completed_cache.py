"""Archive completed hourly checkpoints, verify every byte, then remove duplicates."""
import hashlib,json,shutil,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent.resolve()
TARGET=(ROOT/'work'/'point_in_time_universe31'/'hourly').resolve()
ARCHIVE=(ROOT/'work'/'point_in_time_universe31'/'hourly_checkpoints_verified.zip').resolve()
def main():
    expected_root=(ROOT/'work'/'point_in_time_universe31').resolve()
    assert TARGET.parent==expected_root and ARCHIVE.parent==expected_root and TARGET.is_dir()
    files=sorted(TARGET.glob('*.json'));assert len(files)==563 and not list(TARGET.glob('*.partial'))
    for p in files:assert p.resolve().parent==TARGET and not p.is_symlink()
    entries={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in files}
    temporary=ARCHIVE.with_suffix('.partial')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,arcname=p.name)
        z.writestr('_manifest.json',json.dumps(entries,sort_keys=True))
    with zipfile.ZipFile(temporary,'r') as z:
        assert z.testzip() is None and len(z.namelist())==len(files)+1
        for name,rec in entries.items():
            data=z.read(name);assert len(data)==rec['bytes'] and hashlib.sha256(data).hexdigest()==rec['sha256']
    temporary.replace(ARCHIVE)
    for p in files:p.unlink()
    out={'original_files':len(files),'original_bytes':sum(x['bytes'] for x in entries.values()),
         'archive_bytes':ARCHIVE.stat().st_size,'archive_sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
         'archive':str(ARCHIVE),'each_checkpoint_verified_before_removal':True,'disk_free_bytes':shutil.disk_usage(ROOT).free,
         'note':'Only completed research-generated checkpoint duplicates were archived; raw data outputs and other user files were not modified.'}
    (HERE/'小时缓存归档核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE31_CACHE_COMPRESSED',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
