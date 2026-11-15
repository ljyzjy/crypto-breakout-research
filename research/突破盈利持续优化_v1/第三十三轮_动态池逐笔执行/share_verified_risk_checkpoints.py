"""Hard-link identical risk task snapshots between the two training variants."""
import json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent.parent
BASE=(ROOT/'work'/'point_in_time_universe33').resolve()
def main():
    a=(BASE/'risk_training').resolve();b=(BASE/'risk_backup_training').resolve()
    assert a.parent==BASE and b.parent==BASE and a.is_dir() and b.is_dir()
    count=0
    for src,dst in ((a,b),(b,a)):
        for p in src.glob('*.json'):
            assert p.resolve().parent==src and not p.is_symlink()
            q=dst/p.name
            try:os.link(p,q);count+=1
            except FileExistsError:pass
    print('UNIVERSE33_SHARED_RISK_CHECKPOINTS',count,flush=True)
if __name__=='__main__':main()
