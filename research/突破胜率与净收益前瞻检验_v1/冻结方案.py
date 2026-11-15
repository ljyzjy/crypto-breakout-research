"""Freeze scope from research inputs available by 2026-04-26; no new market prices."""
from pathlib import Path
import hashlib,json
import pandas as pd

HERE=Path(__file__).resolve().parent
manifest=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase2\data\manifest.json')
d=json.loads(manifest.read_text(encoding='utf-8'))
pools=json.loads(Path(d['daily_pools_path']).read_text(encoding='utf-8'))
p=next(x for x in pools if x['date']=='2026-04-26')
cut=int(pd.Timestamp('2026-04-26',tz='UTC').timestamp()*1000)
pool=[];excluded=[]
for rank,entry in enumerate(p['pool'],1):
    s=entry['symbol'];contract=d['mapping'].get(s);q=d['quarantine'].get(s)
    if not contract or (q and int(q['known_ts'])<=cut):
        excluded.append({'symbol':s,'reason':'unmapped_or_already_quarantined'});continue
    pool.append({'symbol':s,'contract':contract,'liquidity_rank':rank})
assert len(pool)==18 and {x['symbol'] for x in pool}.issuperset({'BTCUSDT','ETHUSDT'})
plan={
  'basis':'用户现有15分钟柱内突破研究的两币活跃且同向版本；公开数据，不访问任何账户。',
  'pool':'冻结为2026-04-26研究日池中当时已映射且未隔离的18币；资格排序依据4月25日及以前已知信息。未来不按是否存续或收益剔除，不代表未来每日动态top20。',
  'fixed_pool':pool,'excluded':excluded,
  'warmup':'2026-04-01至2026-04-30仅用于已收盘历史特征。',
  'test':'2026-05-01 00:00 UTC 至 2026-11-01 00:00 UTC，之前 ge 冻结研究截止2026-04-27；本次方案固定前只检查公开数据是否存在，没有读取该期收益。',
  'periods':['2026-05-01至2026-07-31','2026-08-01至2026-10-31','2026-05-01至2026-10-31连续账户'],
  'entry':'继承1分钟收盘首次突破此前16根完整15分钟柱，BTC/ETH同进度笔数均>=1.5倍且同时越过自身16柱同向边界，决策后延迟1分钟尝试且主场景须仍在原突破15分钟柱内；原日内交易时段、每币60分钟事件排除、ATR止损、成本空间、排名和趋势条件保留。',
  'rank_difference':'每小时在固定18币中以已完成小时6小时收益/24小时波动率排序，做多和做空各取强度前三，小时成交额/此前20天同小时中位数>=1.5；使用已完成15分钟EMA20方向和斜率。流动性并列名次使用冻结时顺序，不冒充未来动态现货日池。',
  'variants':[
    {'id':'baseline_2r','entry':'首次突破','target_r':2.0},
    {'id':'target_1r','entry':'首次突破','target_r':1.0},
    {'id':'target_1_5r','entry':'首次突破','target_r':1.5},
    {'id':'confirm_1r','entry':'最初满足双币条件后，额外等下一分钟收盘，目标币仍在边界外、BTC/ETH仍同时活跃及同向，且当前分钟、趋势和排名有效；随后再延迟1分钟且主场景入场须仍在原柱内，止损为两根已完成分钟极值外0.1ATR','target_r':1.0}
  ],
  'costs':['main：每边手续费0.05%＋滑点0.05%，资金费按历史时间与费率另计',
           'double：手续费和滑点各翻倍，资金费不机械翻倍',
           'delay1：主成本再延迟1分钟，允许延迟后超过15分钟柱，并单列越界成交'],
  'account':'复用原账户回放模型，初始1000 USDT、1倍总名义敞口上限、每笔0.25%计划风险、5%回撤减风险、8%回撤停机、日损1.5%暂停、60分钟最长持仓；不得改变原账户或现有模拟。',
  'success':'全期主成本净收益>0、利润因子>1、净胜率>=60%、最大回撤<=15%、至少100笔且至少30个活跃日；双倍成本和额外延迟分别报告净收益，不以压力场景事后改变阈值。无成交或数据缺失不得视为成功。',
  'boundary':'该计划受先前已看历史结果影响；新时间段是在冻结后首次供本研究评估，但不知道其他会话是否看过。精度为分钟，缺盘口与逐秒成交；保留原始失败和缺失，不搜索其他参数。',
  'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()
}
(HERE/'冻结研究方案.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print('FROZEN',len(pool),[(r['symbol'],r['contract']) for r in pool])
