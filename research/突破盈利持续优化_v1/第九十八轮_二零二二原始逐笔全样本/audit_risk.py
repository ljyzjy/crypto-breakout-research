"""Adapt the independent 2022 source parser and arithmetic audit to this batch."""
from pathlib import Path
import sys
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; B=H/'原始逐笔批次'
sys.path.insert(0,str(bulk.R90)); from audit_risk_2022 import independent_read
SOURCE=H.parent/'第八十一轮_八至十月一秒观察/audit_risk.py'


def main():
    text=SOURCE.read_text(encoding='utf-8')
    changes=[('import run_replay as runner','import replay_2022 as runner'),
             ("frame = pd.read_csv(io.BytesIO(body), compression='zip')",'frame = independent_read(body, kind)'),
             ('动态池逐笔信号筛查.parquet','逐笔信号.parquet'),
             ('动态池延迟市价路径.parquet','模拟路径.parquet'),
             ('动态池单位收益与风险.parquet','单位净收益与风险.parquet')]
    for old,new in changes:
        assert text.count(old)>=1,old
        text=text.replace(old,new)
    env={'__name__':'ext98_independent_risk','__file__':str(Path(__file__)),'independent_read':independent_read}
    exec(compile(text,str(SOURCE),'exec'),env);env['H']=H;env['B']=B;env['main']()


if __name__=='__main__':main()
