"""Independently audit alternative-rank risk sources and ledger calculations."""
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
SOURCE = H.parent / '第八十一轮_八至十月一秒观察/audit_risk.py'
sys.path.insert(0, str(R90)); from audit_risk_2022 import independent_read
import replay_extra as extra


def main():
    extra.runner.guard(start=True)
    text = SOURCE.read_text(encoding='utf-8')
    changes = [('import run_replay as runner', 'import replay_2022 as runner'),
               ("assert source['code_sha256'] == sha(H / 'settle_risk.py')", "assert source['code_sha256'] == sha(R90 / 'settle_risk_2022.py')"),
               ("frame = pd.read_csv(io.BytesIO(body), compression='zip')", 'frame = independent_read(body, kind)')]
    for a, b in changes:
        assert text.count(a) == 1, a
        text = text.replace(a, b)
    env = {'__name__': 'ext94_independent_risk', '__file__': str(Path(__file__)), 'independent_read': independent_read}
    exec(compile(text, str(SOURCE), 'exec'), env)
    env.update({'H': H, 'B': H / '一秒回放批次', 'R90': R90})
    env['main']()


if __name__ == '__main__':
    main()
