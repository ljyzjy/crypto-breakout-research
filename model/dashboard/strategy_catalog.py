"""Read-only descriptions of the implemented rules; never used for trade decisions."""
from copy import deepcopy

FREQ = {
    'universe': '固定 BTC/USDT、ETH/USDT；不轮换币种。',
    'allocation': '初始 1,000 USDT；每笔名义投入 100 USDT，最多 2 笔；不加仓、不再平衡，余款留现金。',
    'risk': '单笔 −4% 止损；无固定止盈、无移动止损。退出后该币冷却 6 小时；48 小时内跨币累计 2 次亏损止损，暂停开仓 24 小时。',
    'cadence': '只使用包含 24 根小时 K 线的完整 UTC 日线。日末产生信号，回测下一小时执行；日内仍由引擎处理止损。',
    'cost': 'Freqtrade 小时回测：单边手续费 0.1%，另做过 0.2% / 0.3% 压力情景；未统一叠加固定滑点。模拟盘按公开行情撮合，成交口径不同。',
    'boundaries': '只做现货多头，无杠杆。有效信号要求成交量 > 0；保护期内不开仓。回测区间结束强制平仓计费；历史成交粒度与真实成交不同。',
    'engine': 'Freqtrade · 小时执行',
    'source': 'user_data/strategies/DailyCandidates.py',
}

FROZEN = '冻结的 20 币候选集，按 2022 年 12 月成交额预选，仅用于 2023 年及以后。BTC、ETH、XRP、DOGE、BNB、LTC、MATIC、SOL、HOOK、LINK、ADA、TWT、TRX、CHZ、APT、MASK、SHIB、APE、DOT、FTM；保留历史退市币，不按今天的存续状态筛选。'
HARD = '每日须有前日收盘价、至少 180 天历史、近 30 天至少 28 条记录，且近 30 天日成交额中位数 ≥ 500 万 USDT。'
POOL = '每周一（及回测首日）更新、最多 8 币：已有币流动性排名 ≤ 10 可保留；从前 6 名中补入成交额中位数 ≥ 1,000 万 USDT 的币。每日剔除不满足硬条件的币，不强行补满。'
RESEARCH = {
    'universe': '历史冻结候选集 → 流动性池，最多 8 币。',
    'pool': FROZEN + HARD + POOL,
    'risk': '单笔 −4% 止损；跳空越过止损价按开盘价卖出，日内触发按止损价卖出，再扣滑点。止损后该币冷却 2 个日历日；最低买单 10 USDT。无固定止盈。',
    'cadence': 'T 日决策只读 T−1 日及更早的完整数据，T 日开盘模拟成交；当天高低价只决定成交和止损，不参与当天选币。',
    'cost': '日线研究引擎：初始 1,000 USDT，单边手续费 0.1% + 单边滑点 0.05%；另列 0.2% / 0.3% 手续费压力情景。',
    'boundaries': '20% 是下单时的目标预算，持仓涨跌后允许漂移；空余份额留现金，无杠杆。持仓价格缺失则标记比较无效，不假造退市卖价。区间末按可用价格平仓；未还原历年交易所数量精度与最小金额。',
    'engine': '日线组合研究引擎',
    'source': 'selection-v2/engine.py · selection-v2/protocol.json',
}

CARDS = []


def add(key, title, idea, profile, group='main', status='历史候选 · 未运行', **overrides):
    card = deepcopy(profile)
    card.update(id=key, title=title, idea=idea, group=group, status=status)
    card.update(overrides)
    CARDS.append(card)
    return card


momentum = add('DailyMomentum', '30 日动量', '过去一个月上涨才持有，转弱就退出。', FREQ,
    status='当前模拟策略', entry='日收盘价 ÷ 30 日前收盘价 − 1 > 0，且当前空仓。',
    exit='30 日动量 ≤ 0 卖出；或先触发 −4% 止损。', link='/backtest', link_label='查看历史回测')
add('SpotTrendV1', '小时趋势突破', '小时均线确认方向，再用价格突破入场。', FREQ,
    entry='50 小时均线 > 200 小时均线，且收盘价突破此前 20 小时最高价。',
    exit='收盘价跌破此前 10 小时最低价，或 50 小时均线 < 200 小时均线；另有 −4% 止损。',
    cadence='每根已完成小时 K 线判断，回测下一根执行；突破通道排除当前信号 K 线。',
    source='user_data/strategies/SpotTrendV1.py')
donchian = add('DailyDonchian', '日线唐奇安突破', '突破中期高点入场，跌破短期低点离场。', FREQ,
    entry='日收盘价 > 此前 55 个完整日的最高价；通道不含当日。',
    exit='日收盘价 < 此前 20 个完整日的最低价，或 −4% 止损。')
ma = add('DailyMA', '日线双均线', '短期均价高于长期均价时持有。', FREQ,
    entry='20 日简单均线 > 60 日简单均线；判断状态，不要求当天刚刚金叉。',
    exit='20 日均线 < 60 日均线，或 −4% 止损；两线相等不产生退出信号。')
bollinger = add('DailyBollinger', '布林带回归', '从下轨下方回到通道内时买入，回到中轨退出。', FREQ,
    entry='昨日收盘 < 昨日下轨；今日收盘 > 今日下轨且 < 中轨。中轨为 20 日均线，下轨为中轨 − 2 倍标准差（ddof=0）。',
    exit='日收盘价 ≥ 中轨，或 −4% 止损。')
v1 = add('selection', '选币 V1 · 趋势与波动率', '先筛流动性，再择强币，用波动率分配仓位。', RESEARCH,
    status='研究方案 · 未采用',
    entry='每周从池内筛选：BTC 收盘 > 200 日均线；该币 30 日动量 > 0 且收盘 > 100 日均线。按 60 日动量 ÷ 波动率取前 4 名。',
    exit='每天检查：市场门槛、个币趋势或池资格失效即退出；每周落选也退出；另有 −4% 止损。',
    allocation='总目标 20%，最多 4 币、单币上限 8%；按 60 日波动率倒数分配。每周再平衡，未用额度留现金。',
    sizing='波动率用近 60 日收益率标准差（至少 50 条），计算分数与权重时下限 0.5%。目标减仓须超过现有数量 10%；补仓须达目标金额 10% 且至少 10 USDT。补仓止损价只上调、不放宽。非周一只退出，不填新仓。',
    link='/selection', link_label='查看信息时点审计')
add('liquidity4', '流动性前 4 + 动量', '选流动性强的币，每个币独立判断是否持有。', RESEARCH,
    status='研究方案 · 未采用', universe='历史冻结候选集 → 最多 4 币的流动性池。',
    pool=FROZEN + HARD + '每周一（及回测首日）更新：已有币流动性排名 ≤ 6 保留；从前 4 名中补入成交额中位数 ≥ 1,000 万 USDT 的币，最多 4 币。每日剔除硬条件失效者。',
    entry='每日判断：池内该币 30 日动量 > 0，且不在止损冷却期。',
    exit='30 日动量 ≤ 0、被移出池，或 −4% 止损。',
    allocation='每币预留 5% 账户权益，最多 4 币；不调整已有仓位，空缺留现金。',
    sizing='没有 BTC 均线市场门槛、个币 100 日均线门槛或波动率加权。')
add('relative4', '相对动量前 4', '在流动性池内择强，并用排名缓冲减少轮换。', RESEARCH,
    status='研究方案 · 未采用',
    entry='每周按正的 30 日动量排序：已有持仓仍在前 6 名可保留，再从前 4 名补足，最多 4 币；须通过冷却期。',
    exit='每日动量 ≤ 0 或离开币池即退出；每周不再入选也退出；另有 −4% 止损。',
    allocation='每币预留 5% 账户权益，最多 4 币；不调整已有仓位，空缺留现金。',
    sizing='只在每周一及回测首日补入新币；无 BTC 市场均线门槛、个币均线门槛或波动率加权。')
add('core_satellite', 'BTC / ETH 核心 + 卫星', '主仓留给 BTC、ETH，少量仓位参与强势币。', RESEARCH,
    status='研究方案 · 未采用', universe='BTC、ETH 作为核心；原 8 币流动性池内再选 1 个非核心币。',
    entry='核心每日看 30 日动量 > 0；卫星每周选正动量最高的币，已有卫星仍在前 2 名则保留；均须通过冷却期。',
    exit='核心动量 ≤ 0 或硬资格失效；卫星动量 ≤ 0、离池或周度落选；另有 −4% 止损。',
    allocation='BTC、ETH 各预留 7.5%，卫星预留 5%；最多 3 币。不调整已有仓位，不把空缺份额分给其他币。',
    sizing='核心仍须满足 180 天历史、28/30 条记录与 500 万 USDT 流动性硬门槛，但不受流动性池排名限制。无均线门槛和波动率加权。')

add('baseline', 'BTC / ETH 动量 · 日线对照', '用同一个日线研究引擎隔离选币带来的差异。', RESEARCH,
    group='control', status='研究对照 · 未运行', universe=FREQ['universe'],
    pool='固定 BTC、ETH；不使用动态币池的排名和 180 天 / 流动性硬门槛。须有可计算的 30 日动量。',
    entry='每日 30 日动量 > 0 且通过止损冷却期时入场。',
    exit='每日 30 日动量 ≤ 0，或 −4% 止损。',
    allocation='BTC、ETH 各按入场前账户权益的 10% 下单；最多 2 币，不调整已有持仓。',
    sizing='与正在运行的 DailyMomentum 规则方向相同，但使用权益比例下单、日线止损、2 日冷却与固定滑点；结果不可混当成同一条模拟账户记录。')
add('buyhold20', '20% BTC / ETH 买入持有', '用相同起始风险投入，观察持有不择时的结果。', {},
    group='control', status='历史对照 · 未运行', engine='买入持有对照计算',
    universe=FREQ['universe'], entry='区间开始按首个开盘价，各买入 100 USDT（含买入手续费）。',
    exit='持有至区间结束，按末日收盘价卖出并计卖出手续费。',
    allocation='初始 BTC 10% + ETH 10% + 现金 80%；不再平衡，仓位随价格漂移。',
    risk='不设止损、止盈或冷却期；最大回撤来自持仓价格变化。',
    cadence='仅区间开始和结束交易，不产生中途择时信号。',
    cost='初始 1,000 USDT，单边手续费 0.1%；未额外叠加固定滑点。',
    boundaries='初始 20% 投入对照，不是满仓 BTC / ETH 收益。现金不计息。净值按持仓市值记录，区间末扣卖出费。',
    source='comparison-v2/build_report.py')
add('cash', '全现金对照', '观察没有参与行情时的账户基线。', {},
    group='control', status='研究对照 · 未运行', engine='现金基线',
    universe='不选币。', entry='不买入。', exit='不卖出。', allocation='1,000 USDT 全部保留现金。',
    risk='没有币价持仓回撤；未建模 USDT 脱锚、平台或托管风险。',
    cadence='全区间保持现金。', cost='无交易、无手续费，不计现金利息。',
    boundaries='名义收益和回撤均为 0，不代表真实持有 USDT 没有风险。', source='selection-v2/study.py')

for key, title, parent, entry, exit_rule in [
    ('DonchianLow', '唐奇安 · 44 / 16 日', donchian, '日收盘价 > 此前 44 个完整日最高价（不含当日）。', '日收盘价 < 此前 16 个完整日最低价，或 −4% 止损。'),
    ('DonchianHigh', '唐奇安 · 66 / 24 日', donchian, '日收盘价 > 此前 66 个完整日最高价（不含当日）。', '日收盘价 < 此前 24 个完整日最低价，或 −4% 止损。'),
    ('MALow', '双均线 · 16 / 48 日', ma, '16 日均线 > 48 日均线；不要求当日刚交叉。', '16 日均线 < 48 日均线，或 −4% 止损。'),
    ('MAHigh', '双均线 · 24 / 72 日', ma, '24 日均线 > 72 日均线；不要求当日刚交叉。', '24 日均线 < 72 日均线，或 −4% 止损。'),
    ('MomentumLow', '动量 · 24 日', momentum, '日收盘价 ÷ 24 日前收盘价 − 1 > 0。', '24 日动量 ≤ 0，或 −4% 止损。'),
    ('MomentumHigh', '动量 · 36 日', momentum, '日收盘价 ÷ 36 日前收盘价 − 1 > 0。', '36 日动量 ≤ 0，或 −4% 止损。'),
    ('BollingerLow', '布林带 · 16 日', bollinger, '昨日收盘 < 昨日下轨；今日收盘 > 今日下轨且 < 中轨。中轨为 16 日均线，下轨 = 中轨 − 2 倍标准差（ddof=0）。', '日收盘价 ≥ 中轨，或 −4% 止损。'),
    ('BollingerHigh', '布林带 · 24 日', bollinger, '昨日收盘 < 昨日下轨；今日收盘 > 今日下轨且 < 中轨。中轨为 24 日均线，下轨 = 中轨 − 2 倍标准差（ddof=0）。', '日收盘价 ≥ 中轨，或 −4% 止损。'),
]:
    # Copies keep every inherited component visible, rather than requiring another card.
    child = add(key, title, '预先设定的邻近参数，用于检查参数敏感性。', parent,
        group='diagnostic', status='参数诊断 · 未采用', entry=entry, exit=exit_rule,
        parent=parent['id'], source='user_data/strategies/DailyCandidates.py')
    child.pop('link', None)
    child.pop('link_label', None)

diagnostics = [
    ('no_market_gate', 'V1 · 移除市场门槛', '仅移除 BTC 200 日均线过滤。', dict(
        entry='每周从池内筛选：该币 30 日动量 > 0、收盘 > 100 日均线；按 60 日动量 ÷ 波动率选前 4。无需 BTC 在 200 日均线上方。',
        exit='个币趋势或池资格失效即每日退出；周度落选或 −4% 止损也退出。BTC 均线不触发退出。')),
    ('no_ma100', 'V1 · 移除个币均线', '仅移除个币 100 日均线过滤。', dict(
        entry='每周要求 BTC 收盘 > 200 日均线、个币 30 日动量 > 0；按 60 日动量 ÷ 波动率选前 4，无个币 100 日均线条件。',
        exit='BTC 市场门槛失效、个币动量 ≤ 0 或池资格失效即每日退出；周度落选或 −4% 止损也退出。')),
    ('daily_vacancy_entry', 'V1 · 每日填补空位', '仅允许周中用原规则填补空仓位。', dict(
        entry='每周按 V1：BTC > 200 日均线、个币动量 > 0 且价 > 100 日均线，以 60 日动量 ÷ 波动率选前 4；周中也按同一筛选和评分补空位。',
        sizing='周中保留合格持仓、不因排名强制换币；在剩余 20% 目标预算内，以波动率倒数配置空位，单币 ≤ 8%。每周仍再平衡：减仓差额 > 现仓 10%；补仓 ≥ 目标 10% 且 ≥ 10 USDT。波动率为 60 日（至少 50 条），下限 0.5%；补仓止损只提高。')),
    ('equal_weights', 'V1 · 等权分仓', '仅把波动率倒数权重换成等权。', dict(
        allocation='每币目标 min(20% ÷ 入选币数，8%)，最多 4 币；每周再平衡，剩余留现金。',
        sizing='排序仍用 60 日动量 ÷ 波动率，波动率为 60 日（至少 50 条）、下限 0.5%。减仓差额 > 现仓 10%；补仓 ≥ 目标 10% 且 ≥ 10 USDT。补仓止损只提高。非周一不填新仓。')),
    ('no_rebalance', 'V1 · 不调整已有仓位', '仅关闭已有持仓的周度补仓和减仓。', dict(
        allocation='总目标 20%，最多 4 币、单币入场目标 ≤ 8%；以 60 日波动率倒数分配新仓。已有仓位不补、不减，允许漂移。',
        sizing='仍每周选币；退出和新仓规则不变。波动率为 60 日（至少 50 条），下限 0.5%。不补仓也就不会因补仓抬高止损价。非周一不填新仓。')),
]
for key, title, idea, changes in diagnostics:
    child = add(key, title, idea, v1, group='diagnostic', status='单项诊断 · 未采用',
                parent='selection', **changes)
    child.pop('link', None)
    child.pop('link_label', None)


SHORT = dict(FREQ,
    engine='短线统一研究引擎', source='short-term-research/st_engine.py · protocol.json',
    cadence='完整小时收盘后决策，下一执行 K 线开盘成交；全历史用小时执行，2025 年以后另做 5 分钟细化与额外 5 分钟信号延迟。',
    cost='初始 1,000 USDT，每笔名义投入 100 USDT、手续费另计；单边手续费 0.1% + 滑点 0.05%，另列手续费 0.2% / 0.3%。',
    boundaries='固定 BTC/ETH、最多 2 仓、无杠杆。区间末强制平仓计费；遇持仓缺失价格标记比较受限。当前只有历史研究，未采用或切换模拟账户。',
    link='/short-term', link_label='查看短线回测与因子检验')
short_a=add('short_breakout','短线 A · 小时突破','突破过去一天的高点，参与短趋势。',SHORT,
    status='已回测 · 未采用',entry='小时收盘价 > 此前 24 小时最高价，通道排除当前小时。',
    exit='收盘价 < 此前 6 小时最低价，或持仓达到 48 小时；另有 4% 止损。')
add('short_pullback','短线 B · 趋势回撤','趋势向上时，等待价格重新站上成交均价。',SHORT,
    status='已回测 · 未采用',entry='EMA24 > EMA72；上一小时收盘 ≤ 当时 VWAP24，本小时收盘 > 当前 VWAP24。',
    exit='EMA24 ≤ EMA72，或收盘达到此前 24 小时高点，或持仓达到 24 小时；另有 4% 止损。',
    sizing='EMA adjust=False，至少 720 个连续有效小时预热。VWAP24 使用 24 小时成交额之和 / 成交数量之和。')
short_c=add('short_reversion','短线 C · 震荡反转','仅在震荡条件下，等待偏离后的恢复确认。',SHORT,
    status='已回测 · 未采用',entry='ER24 ≤ 0.25；上一小时 VWAP 偏离 < −2 ATR，本小时恢复到 ≥ −1 ATR。',
    exit='小时收盘达到 VWAP24，或持仓达到 6 小时；另有 4% 止损。',
    sizing='ER24 = 24 小时净价格变化绝对值 / 各小时价格变化绝对值之和；偏离 = (收盘 − VWAP24) / ATR14。ATR14 为小时真实波幅的 14 期简单均值。')
add('short_breakout_volume','短线 A · 加成交额确认','仅增加成交活跃度确认，独立检查增量。',short_a,
    group='diagnostic',status='已回测诊断 · 未采用',parent='short_breakout',
    entry='小时收盘突破此前 24 小时高点，且当前成交额 / 此前 168 小时成交额中位数 ≥ 1.5。')
add('short_breakout_flow','短线 A · 加主动买盘确认','仅增加主动买入占比确认，独立检查增量。',short_a,
    group='diagnostic',status='已回测诊断 · 未采用',parent='short_breakout',
    entry='小时收盘突破此前 24 小时高点，且最近 4 小时主动买入成交额占总成交额 > 50%。',
    sizing='TBI4 = 2 × 主动买入成交额 / 总成交额 − 1；只使用已完成小时。该量不是资金净流入或挂单簿 OFI。')


add('breakout_mom30','A 优化① · 个币方向过滤','先确认个币中期方向，再接受小时突破。',short_a,
    group='diagnostic',status='优化已回测 · 未通过采用条件',parent='short_breakout',
    entry='原 24 小时突破条件，另要求最后完整 UTC 日线 30 日动量 > 0；日线信息在完整日结束后才可用。',
    source='short-term-research/optimization-v1/opt_engine.py · protocol.json',link='/short-term?mode=breakout_mom30')
add('breakout_4h_entry','A 优化② · 每四小时入场','减少新开仓检查次数，保留小时级退出。',short_a,
    group='diagnostic',status='优化已回测 · 未通过采用条件',parent='short_breakout',
    entry='原小时突破信号，仅在 UTC 00/04/08/12/16/20 时检查新开仓；使用此前已完成小时数据。',
    cadence='指标窗口仍为小时长度；新开仓每 4 小时检查，信号退出仍逐小时，止损按小时/5分钟执行。延迟模式仍保留原信息时刻。',
    source='short-term-research/optimization-v1/opt_engine.py · protocol.json',link='/short-term?mode=breakout_4h_entry')
add('reversion_cost_room','C 优化③ · 成本空间过滤','回归目标的价格空间须先覆盖往返成本。',short_c,
    group='diagnostic',status='优化已回测 · 未通过采用条件',parent='short_reversion',
    entry='原震荡反转信号，且最后完整小时 VWAP24 / 收盘价 − 1 > 预计往返持平涨幅；基础成本下约 0.30045%。',
    sizing='持平涨幅 = (1+s)(1+f)/[(1−s)(1−f)]−1；s=0.05%，f为当前手续费情景。目标空间不是预期收益或成交保证；压力情景阈值随成本机械变化。',
    source='short-term-research/optimization-v1/opt_engine.py · protocol.json',link='/short-term?mode=reversion_cost_room')



PUBLIC = dict(SHORT, source='short-term-research/public-research-v1/public_engine.py · protocol.json',
    link='/research', link_label='查看公开方法与杠杆研究', engine='公开方法固定规则适配')
add('multi_momentum','公开方法① · 30/60/90 日动量共识','多个趋势期限投票，避免只依赖一个观察窗口。',PUBLIC,
    status='历史门槛通过 · 独立前瞻观察，未优于原策略',
    entry='完整日线30/60/90日收益至少两项严格为正；91个连续有效日预热。',
    exit='少于两项为正，或4%价格止损。无固定持有期限。',cadence='只在完整UTC日结束后决策；次小时或5分钟延迟执行。')
add('ewmac_ensemble','公开方法② · 4小时均线趋势组合','三组固定速度的均线方向投票。',PUBLIC,
    status='未通过双倍费用门槛 · 并列观察，不采用',entry='EMA8>32、16>64、32>128，至少两组成立。',
    exit='少于两组成立，或4%价格止损；无固定持有期限。',
    sizing='等票权，EMA adjust=True；1,024根连续完整4小时预热，非拟合权重。',cadence='只在完整4小时结束后决策；价格止损仍按小时/5分钟处理。')
add('channel_ensemble','公开方法③ · 4小时价格通道组合','价格处于多个通道的上半部时跟随趋势。',PUBLIC,
    status='现货历史门槛通过 · 合约计费后微亏，未采用',
    entry='40/80/160根收盘价各算(close−通道中点)/通道宽度，再以窗口四分之一EMA平滑，等权均值>0。',
    exit='均值≤0或4%价格止损；无固定持有期限。',sizing='480根连续完整4小时预热，不拟合权重。',cadence='仅完整4小时结束后决策。')
for mode,title in [('DailyMomentum','30日动量'),('multi_momentum','多周期动量'),('ewmac_ensemble','均线趋势组合'),('channel_ensemble','通道趋势组合')]:
    parent=next(c for c in CARDS if c['id']==mode)
    add('perpetual_'+mode,'合约研究 · '+title,'同一套现货信号在真实合约价格上执行，检查杠杆和资金费成本。',parent,
        group='diagnostic',status='杠杆历史研究 · 未连接账户',parent=mode,
        allocation='初始1,000 U，每仓固定100 U逐仓保证金；名义额按1/2/3倍为100/200/300 U，最多2仓，余款现金。无加仓或复利。',
        risk='4%是币价止损；相应保证金损失随杠杆扩大。沿用冷却和暂停规则；5分钟标记价最低点检查7%抵押品/名义额压力门槛。',
        cost='沿用单边手续费0.1/0.2/0.3%及滑点0.05%；另逐次计入历史真实资金费率。边界新入场保守收取正资金费。',
        cadence='现货完整小时/日/4小时信号，在下一合约5分钟时点执行；另做5分钟延迟。',
        boundaries='5%维持保证金压力+2%费用储备为研究假设，未重建历史交易所档位；无账户下单，不等于整个账户1/2/3倍敞口。',
        engine='USDT永续合约账本重放与抵押品核对',source='short-term-research/leverage-v1/leverage_engine.py · protocol.json',link='/research',link_label='查看杠杆对比')



RISK_BUDGET=dict(SHORT,source='short-term-research/risk-budget-v1/risk_engine.py · protocol.json',
    entry='沿用原30日动量 > 0的完整UTC日信号；仓位计算只读当时已经完成的数据。',
    exit='沿用30日动量≤0退出或4%价格止损；无固定持有期限。',
    cadence='完整日结束后决策，次小时/5分钟执行；持仓期间不重新平衡，不加仓。',
    cost='初始1,000 U；单边手续费0.1%+滑点0.05%，另列手续费0.2/0.3%；手续费按实际下单金额计算。',
    boundaries='固定BTC/ETH，最多两仓，无借款。波动率=20个完整日对数收益标准差ddof1，需连续21个有效日；缺失或零波动不开仓；最低订单10 U。',
    link='/research#risk-budget',link_label='查看仓位研究')
add('fixed200','仓位对照 · 每仓200 U','原30日动量固定提高自有资金投入，用作更高仓位的对照。',RISK_BUDGET,
    group='control',status='历史对照 · 未切换模拟',allocation='每仓固定200 U，最多400 U入场金额；手续费另计，不借款。',link='/short-term?mode=fixed200')
add('vol_cap100','风险预算① · 高波动减仓','高波动时减少投入，单币不超过原100 U。',RISK_BUDGET,
    status='历史门槛通过 · 收益回撤取舍，未采用',allocation='每仓金额=min(100,2/σ)，余款现金，不转给另一币。',link='/short-term?mode=vol_cap100')
add('vol_target200','风险预算② · 固定波动预算','每币每日波动风险预算2 U，低波动时可提高入场金额。',RISK_BUDGET,
    status='历史门槛通过 · 回撤降低但收益略低，未采用',allocation='每仓金额=min(200,2/σ)，单币最多200 U，最多两仓400 U入场金额；风险预算只在入场计算，不承诺持有期间风险恒定。',link='/short-term?mode=vol_target200')
add('inverse_vol_pair','风险预算③ · 双币风险分配','按逆波动权重分配BTC/ETH的入场预算。',RISK_BUDGET,
    status='历史门槛通过 · 未优于原策略，未采用',allocation='200 U总入场预算，权重=(1/σ_i)/Σ(1/σ)；单币上限150 U，下单时再扣除已有仓位入场金额占用，余款不重分配。',link='/short-term?mode=inverse_vol_pair')


for budget in (3,4):
    add('vol_budget'+str(budget),'增额试验 · 波动预算'+str(budget)+' U',
        '提高原30日动量的资金利用率，单独检查收益与15%回撤门槛。',RISK_BUDGET,
        group='diagnostic',status='独立历史研究 · 不修改模拟',
        allocation=f'入场金额=min({budget*100},{budget}/σ)，单币上限{budget*100} U；现金约束、最多两仓，不加仓、不复投。',
        source='short-term-research/coin-lab-v1/coin_engine.py · protocol.json',link='/coin-lab',link_label='查看年化与15%回撤比较')
for budget in (2,3):
    add('auto_budget'+str(budget),'全池自动选币 · 波动预算'+str(budget)+' U',
        '从历史公开币池按流动性与风险调整动量选币，再进行每日择时和波动分仓。',RISK_BUDGET,
        status='全池独立回测 · 未部署模拟',
        universe='Binance公开归档中的全部USDT现货历史交易对，保留退市币；只用当时有记录的币。',
        pool='排除稳定/法币与成对杠杆代币；须连续90日有效记录、30日成交额中位数≥1000万U。每周一及区间首日选流动性前20，再选正30日动量/20日波动率评分前2；其他日保持周度集合。',
        entry='所选币30日动量>0，使用前一完整日数据；次执行开盘入场。',
        exit='动量≤0、前日无效、退出周度所选集合，或4%价格止损；区间末计费平仓。',
        allocation=f'初始1000U；入场金额=min({budget*100},{budget}/σ)，最多两仓，现金支付，无借款，无加仓。',
        boundaries='公开归档全池不等于全球所有币。使用历史归档快照；持仓价格缺失使比较无效，不提前知道退市。历史已被研究，须独立前瞻验证。',
        source='short-term-research/coin-lab-v1/automatic_engine.py · automatic-protocol-v2.json',link='/coin-lab',link_label='查看每日选币与完整账本')

POOL_OPT = dict(next(c for c in CARDS if c['id']=='auto_budget2'),
    engine='历史全池逐日选币 · 小时/5分钟执行账本',
    sizing='σ为最近20个完整日对数收益的样本标准差（ddof=1），须连续21个有效日；仅使用决策时已完成的数据。最低买单10U，最多两仓，现金约束、不借款。',
    source='short-term-research/pool-optimization-v1/pool_engine.py · protocol.json',
    link_label='查看亏损诊断、固定比较与逐笔账本',
    boundaries='沿用638币历史快照和同一成本；不按今日存活名单筛选，不按事后盈亏剔除币。四个独立改动和唯一组合事先固定，42个场景全部保留。历史已被反复研究，通过门槛仍须新数据验证；当前模拟不变。')
slow_pool=add('pool_slow_selection','全池改进① · 较慢趋势选币','用较长趋势评分，并跳过最近一周的涨幅。',POOL_OPT,
    status='本轮历史门槛通过 · 年化5.75%，未切换模拟',
    pool='同一历史USDT池、排除表、90日有效记录和30日成交额中位数≥1000万U；流动性前20中按(C[d−7]/C[d−60]−1)/20日波动率排序。该评分收益及30日动量均须为正；每周一及区间首日选前2。d为上一完整UTC日。',
    link='/coin-lab?mode=pool_slow_selection')
gate_pool=add('pool_market_gate','全池改进② · 市场方向择时','只对新开仓增加BTC中期方向门槛。',POOL_OPT,
    status='独立改动仍亏损 · 未通过门槛',
    entry='原周度所选币30日动量>0，另须BTC上一完整UTC日30日收益>0；次执行开盘入场。现有仓位不因BTC门槛失效而被强制卖出。',
    link='/coin-lab?mode=pool_market_gate')
retry_pool=add('pool_weekly_retry','全池改进③ · 止损后延迟重试','同一币止损后等到下一周，减少反复入场。',POOL_OPT,
    status='独立改动仍亏损 · 未通过门槛',
    risk='亏损价格止损后，该币冷却至严格晚于止损确认时刻的下一周一00:00 UTC，且至少6小时。保留48小时内两次亏损止损触发全局24小时暂停；最多两仓、4%价格止损。',
    link='/coin-lab?mode=pool_weekly_retry')
vol_pool=add('pool_vol_stop','全池改进④ · 止损与仓位配套','按波动率设止损距离，并限制每仓计划损失。',POOL_OPT,
    status='独立改动仍亏损 · 未通过门槛',
    exit='30日动量≤0、前日无效或离开周度集合退出；价格止损距离为clip(2×入场已知20日波动率,4%,20%)。区间末计费平仓。',
    allocation='入场金额=min(200,4/止损距离)U，最多两仓；每仓计划价格止损风险≤4U。止损及金额仅入场时确定，不加仓、不事后放宽止损。',
    risk='原6小时冷却及48小时两次亏损止损触发24小时全局暂停不变。价格跳空、滑点及费用可能使实际损失超过4U计划；20%是止损距离上限，不是账户回撤。',
    link='/coin-lab?mode=pool_vol_stop')
add('pool_combined','全池改进⑤ · 预先固定组合','同时采用较慢选币、市场过滤、延后重试和风险分仓。',POOL_OPT,
    status='本轮历史门槛通过 · 年化3.76%，未切换模拟',
    pool=slow_pool['pool'],entry=gate_pool['entry'],exit=vol_pool['exit'],allocation=vol_pool['allocation'],
    risk='亏损止损后等到下一周一且至少冷却6小时；保留48小时两次亏损止损触发24小时全局暂停。采用入场固定的波动止损，费用及跳空可突破4U计划损失。',
    link='/coin-lab?mode=pool_combined')

ROTATION=dict(slow_pool,source='short-term-research/rotation-leverage-v1/rotation_engine.py · protocol.json',
    engine='四版本现货/USDT永续独立账本',
    allocation='现货入场金额/永续逐仓保证金=min(200,2/σ)U；永续名义额=保证金×1至10倍。最多两仓，现金约束，不加仓、不自动补保证金。倍数不是全账户名义敞口。',
    cost='初始1000U，单边手续费0.1%+滑点0.05%；另测双倍/三倍手续费。永续额外按真实历史时点及间隔结算资金费，边界新仓只支付正资金费、不领取负资金费。',
    risk='4%价格止损；退出后6小时冷却，48小时两次亏损止损触发24小时暂停。永续标记低点触及7%抵押品/名义额压力线则中止并隐藏完整区间收益；该线是研究假设，不是还原的真实交易所强平价。',
    boundaries='使用同一638币历史日线信号及成本；实际永续价格和标记价执行/估值，没有对应合约的币留现金。历史保证金/强平费档位未完整重建。固定28现货+240永续场景；过去历史已被研究，未更改模拟。',
    link='/rotation-lab',link_label='查看四版本与1至10倍完整比较')
add('rotation_slow_base','四版本① · 较慢选币基准','保持上一轮较慢选币规则，建立现货与永续对照。',ROTATION,status='固定研究 · 未切换模拟')
add('rotation_rank_buffer','四版本② · 实际持仓排名缓冲','减少排名轻微变动导致的换仓，单独验证净收益。',ROTATION,status='固定研究 · 未切换模拟',
    pool='原历史资格/成交额门槛和较慢评分不变。每周先保留实际持仓中合格排名前4的币，再从前2补空位，最多两币；未持有的第3/4名不直接进入。非周一维持集合。区间首日按当时信息初始化。')
add('rotation_delayed_retry','四版本③ · 较慢选币延迟重买','仅增加止损后等到下周的重试限制。',ROTATION,status='固定研究 · 未切换模拟',
    risk='亏损价格止损确认后，该币等至严格晚于确认时刻的下一周一00UTC，且至少冷却6小时；原全局暂停及4%止损不变。永续标记低点触及7%抵押品压力线则中止，不展示完整区间收益。')
add('rotation_btc_eth','四版本④ · BTC/ETH同预算对照','用相同保证金/金额规则，检查全池轮换的增量价值。',ROTATION,group='control',status='固定对照 · 未切换模拟',
    universe='固定BTCUSDT、ETHUSDT；永续执行对应同名合约。',pool='不使用全池流动性、90日资格或相对排名条件；须有完整可计算的30日动量和20日波动率。',
    entry='上一完整UTC日30日动量>0，且现金、保护期及对应市场价格满足要求。',exit='30日动量≤0、前日价格无效或4%价格止损；区间末计费平仓。')

SHORT_FACTOR=dict(FREQ,universe='固定BTCUSDT、ETHUSDT永续验证池；不代表全池自动选币。',
    pool='两个币独立触发信号，最多两仓；同一币不同时持有多空。',
    allocation='初始1000U；每次保证金=min(200,2/前20日波动率)，名义额=保证金×1至10倍；无加仓、无自动补保证金。',
    risk='双向4%不利价格止损；退出后6小时冷却，48小时两次亏损止损触发24小时暂停。标记低点/高点分别检查多头/空头7%抵押品压力线；触线中止隐藏完整收益。',
    cost='单边0.1%手续费+0.05%滑点，另测双倍/三倍手续费；实际资金费按多空方向计入，边界新仓只付不收。',
    boundaries='Marco公开课程提供扫高低点后反转的方向；此为自定义价格形态近似，不是原策略完整复现。FHAT及99.9%胜率未核实。固定240场景，未改变原模拟。',
    engine='独立多空永续研究账本',source='short-term-research/short-factor-v1/factor_engine.py · protocol.json',
    link='/short-factor',link_label='查看多空因子与1至10倍验证')
add('factor_long_control','多空因子① · 原只做多对照','复用上轮BTC/ETH永续结果。',SHORT_FACTOR,group='control',status='固定对照 · 未切换模拟',
    entry='前一完整日30日动量>0做多。',exit='每日动量不再为正或4%止损退出。',cadence='每日一次方向决策；5分钟价格执行与风险检查。')
add('factor_momentum_ls','多空因子② · 30日动量多空','单独检查开放空头的增量贡献。',SHORT_FACTOR,status='固定研究 · 未切换模拟',
    entry='前一完整日30日动量>0做多，<0做空；保护期内不入场。',exit='每日方向不同/无效或4%止损退出；冷却后方可开新仓。',cadence='每日一次方向决策；5分钟价格执行与风险检查。')
SWEEP_ENTRY='过去24个完整小时最高/最低点，不含信号小时；最近触及距信号至少6小时。小时低点扫过旧低且收盘收回做多，扫高跌回做空；同时满足两侧则不交易。强度=收回距离/前14小时ATR。'
add('factor_sweep_ls','多空因子③ · 扫高低点后收回','测试流动性陷阱思路的可计算价格代理。',SHORT_FACTOR,status='固定近似 · 未切换模拟',
    entry=SWEEP_ENTRY,exit='反向反转信号、持仓满24小时或4%止损退出。',cadence='1小时收盘确认，下根5分钟开盘入场；另测延迟5分钟。')
add('factor_sweep_trend','多空因子④ · 反转加动量方向','检验原动量方向能否过滤反转噪声。',SHORT_FACTOR,status='固定近似 · 未切换模拟',
    entry=SWEEP_ENTRY+'仅当方向与前一完整日30日动量同向时入场。',exit='反向反转信号、持仓满24小时、每日动量方向不符或4%止损退出。',cadence='1小时反转信号，日级趋势过滤；下根5分钟开盘执行。')

DYNAMIC=dict(SHORT_FACTOR,
    engine='固定底仓与逐笔额外仓永续研究账本',
    source='short-term-research/dynamic-leverage-v1/dynamic_engine.py · protocol.json',
    entry='上一完整UTC日30日动量为正做多、为负做空；原全局保护及冷却内不入场。',
    exit='底仓每日方向改变或4%止损退出。区间末计费平仓。',
    cadence='每日00UTC使用已完成日线决策，下根5分钟开盘执行；每5分钟检查风险，另测延迟5分钟。',
    boundaries='固定BTC/ETH验证池，5版本×6场景共30次。底仓1×；5×指相对底仓数量上限，不是账户总杠杆。历史已研究，尚无独立新样本；15%历史回撤门槛不保证未来，未更改当前模拟。',
    link='/dynamic-leverage',link_label='查看条件杠杆、历史决策与完整账本')
for multiple in (1,2,5):
    add('dynamic_fixed'+str(multiple),'条件杠杆对照 · 固定'+str(multiple)+'×','用相同底仓规则、数据和成本分离单纯放大仓位的效果。',DYNAMIC,
        group='control',status='历史风险门槛通过 · 未部署' if multiple==1 else '压力回撤超过15% · 未通过',
        allocation=f'初始1000U；每币保证金=min(200,2/20日波动率)，入场名义额=保证金×{multiple}；最多两币，无加仓、无自动补保证金。')
BOOST_ALLOC='初始1000U；每币底仓保证金=min(200,2/20日波动率)，基础名义额等于保证金。额外每笔加0.5份底仓数量，与底仓共享该币原保证金；逐笔付费，不自动补保证金。实际敞口受价格漂移影响。'
BOOST_GATE='底仓持有至少24小时且按上一已知标记收盘扣累计资金费/入场费后净浮盈；账户回撤<5%、全局保护和额外仓冷却已结束，拟加仓后的组合到止损损失含预计退出成本≤净值2%。按BTC、ETH顺序分配预算。'
BOOST_RISK='底仓4%止损、退出后6小时冷却及48小时两次亏损止损触发24小时暂停不变。额外仓各设4%价格止损；每日条件降级撤多余仓，账户已知回撤≥8%则下根5分钟开盘撤全部额外仓；底仓退出一并退出。每次额外仓退出后冷却24小时。共享抵押品触及7%压力线中止并隐藏完整收益；2%预算及8%触发线不能保证最大回撤。'
LOW_VOL='前20日对数收益波动≤其过去120期中位数，且5日波动≤20日波动；全部使用完整已知日线，预热不足时保持1×。'
add('dynamic_vol_only','条件杠杆① · 低波动至1.5×','只增加低波动判断，作为机制对照。',DYNAMIC,
    status='历史门槛通过 · 年化9.15%，未部署',allocation=BOOST_ALLOC+'仅允许一笔额外仓，最高1.5份。',
    entry=DYNAMIC['entry']+LOW_VOL+BOOST_GATE,risk=BOOST_RISK,exit=BOOST_RISK)
add('dynamic_tiered','条件杠杆② · 多重确认上限5×','平时1倍；条件与风险预算同时允许，才逐档加仓。',DYNAMIC,
    status='本轮主要候选通过 · 年化11.29%，未部署',allocation=BOOST_ALLOC+'最高8笔额外仓，共5份底仓数量；无需加满。',
    entry=DYNAMIC['entry']+LOW_VOL+'低波动允许1.5×；另需10/30/60日动量均与仓位同向、上一日涨跌不超过2倍日波动、决策前24小时已结算的方向付费率≤0.03%，才将上限提高至5×。'+BOOST_GATE,
    risk=BOOST_RISK,exit=BOOST_RISK)

POOL_DYNAMIC=dict(DYNAMIC,universe=POOL_OPT['universe'],
    pool=slow_pool['pool'],source='short-term-research/pool-dynamic-v1/pool_dynamic_engine.py · protocol.json',
    boundaries='同一638币历史归档、费用和资金费。保持原全池正动量做多；BTC/ETH多空仅作方向不同的参考。全区间缺少标记价格时中止、不按盈利删币；缺口前公共子区间截至2026-04-26，由数据完整性提前确定。80场景全部保留，历史非独立样本外，当前模拟未改。',
    link='/pool-dynamic',link_label='查看全池动态杠杆与历史选币审计')
for selector,label in [('slow_base','较慢趋势'),('rank_buffer','排名缓冲'),('delayed_retry','止损后延迟重买')]:
    for variant in ('fixed1','tiered'):
        dyn=variant=='tiered'
        extra='亏损底仓价格止损后，冷却至严格晚于确认时刻的下一周一00UTC，且至少6小时。' if selector=='delayed_retry' else ''
        pool_rule=next(c['pool'] for c in CARDS if c['id']=='rotation_rank_buffer') if selector=='rank_buffer' else slow_pool['pool']
        add('pool_dynamic_'+selector+'_'+variant,'全池杠杆 · '+label+(' · 动态上限5×' if dyn else ' · 1×'),
            '沿用原选币和重买规则，配对检查额外杠杆的净收益与回撤。',POOL_DYNAMIC,
            group='main' if dyn else 'control',status='全区间完整性不足 · 固定子区间研究，未部署',pool=pool_rule,
            entry='周度所选币上一完整日30日动量>0，现金与冷却满足时做多；每日方向不再为正或离开周度集合退出。'+(LOW_VOL+'低波动允许1.5×；10/30/60日动量同向、上一日涨跌不超过2倍日波动、此前24小时已结算方向付费率≤0.03%时上限5×。'+BOOST_GATE.replace('按BTC、ETH顺序','按原全池币种代码排序') if dyn else ''),
            allocation=BOOST_ALLOC+'最多8笔额外0.5份仓位，数量上限5份；按原币种代码顺序分配组合风险预算。' if dyn else '初始1000U，保证金=min(200,2/20日波动率)，名义仓位等于保证金；最多两币，不加仓、不自动补保证金。',
            risk=(BOOST_RISK if dyn else ROTATION['risk'])+extra,
            exit='动量不再为正、离开所选集合或4%价格止损退出；区间末计费平仓。'+('额外仓条件降级、4%独立止损或账户已知回撤≥8%时减仓；底仓退出时一并退出。' if dyn else ''))

ACADEMIC=dict(POOL_DYNAMIC,
    cost='单边官方普通用户USDT永续Taker标准手续费0.05%，按实际成交名义额收取；滑点估计0.05%单列，历史资金费逐笔结算。压力手续费0.10%/0.15%；未读取账户VIP/BNB折扣，未逐期重建历史优惠。',
    source='short-term-research/selection-data-gate-v2/availability_engine.py · protocol.json',
    link='/selection-research',link_label='查看小时选币、排名与完整回测',
    engine='小时选币 · 5分钟永续执行 · 独立研究账本',
    boundaries='14版本×6场景；保留原始84条结果及用户授权的数据可用性修订。已结束成交柱有交易但缺标记收盘时，从柱结束后隔离该币，本轮不自动恢复；按原评分递补，所有币统一规则。归档缺失不代表当时线上停服。持仓估值或当前成交数据缺失仍中止。历史已研究，当前模拟不变。')
ACADEMIC_RULES={
    'control':'原较慢动量=(7日前收盘/60日前收盘−1)/20日波动率。',
    'liquidity':'原动量与流动性代理的截面百分位等权。流动性代理=负的30日平均(绝对日收益/成交额)，不是实测盘口价差。',
    'continuity':'原动量与过去30期上涨日比例的截面百分位等权；是连续信息思想的自定义近似。',
    'residual':'用过去60期收益估计对BTC的beta，扣除慢动量中的BTC成分，再除以20期残差波动；残差方差为零记零分。',
    'combined':'原动量、流动性代理、上涨日比例、BTC残差动量四项截面百分位等权；权重预先固定。'}
for selector,label in [('control','原动量'),('liquidity','流动性代理'),('continuity','趋势连续性'),('residual','BTC残差动量'),('combined','四因子等权')]:
    for cadence in (('hourly','weekly') if selector in ('control','combined') else ('hourly',)):
        for variant in ('fixed1','tiered'):
            dyn=variant=='tiered';hourly=cadence=='hourly'
            add('academic_'+selector+'_'+cadence+'_'+variant,'选币研究 · '+label+(' · 每小时' if hourly else ' · 每周')+(' · 动态5×' if dyn else ' · 1×'),
                '从公开研究提取少量因子，以同数据和成本检查净收益增量。',ACADEMIC,
                group='main' if selector=='combined' and hourly else 'control' if selector=='control' else 'diagnostic',
                status='固定研究与数据隔离修订 · 未替换当前模拟',
                pool='前一完整日资格：90个连续有效日、30日成交额中位数≥1000万U、流动性前20，保留30日与60日跳过7日动量均为正的币。'+ACADEMIC_RULES[selector]+'按分数选两币，最终同分按币种代码排序。',
                cadence=('每小时使用刚结束小时柱重新评分；30/60日跨度不改为小时。' if hourly else '每周一和区间首日重选，每日检查动量。')+'名次不变不强制换仓；仓位波动预算仍来自前一完整日。杠杆每天评估，5分钟检查风险。',
                entry='入选且正动量、现金、冷却及可用数据满足时做多。'+(LOW_VOL+'低波动至1.5×，趋势、冲击和资金费条件通过才允许上限5×。'+BOOST_GATE.replace('按BTC、ETH顺序','按币种代码排序') if dyn else ''),
                allocation=BOOST_ALLOC+'上限5份底仓数量，最多两币。' if dyn else '初始1000U；每币底仓保证金=min(200,2/前一日20日波动率)，名义仓位等于保证金，最多两币；不加仓、不自动补保证金。',
                exit='落选、动量不再为正或4%价格止损退出；区间末计费平仓。'+(BOOST_RISK if dyn else ''),
                risk=BOOST_RISK if dyn else ROTATION['risk'])


for card in list(CARDS):
    if card['id'].startswith('academic_') and '_hourly_' in card['id']:
        new=deepcopy(card)
        new.update(id=card['id'].replace('_hourly_','_12h_'),title=card['title'].replace('每小时','每12小时'),
            idea='按用户指定的12小时频率，与相同评分的小时版配对比较。',
            cadence='UTC00:00和12:00（北京时间08:00和20:00）使用最近已收盘小时柱重排、检查动量和换仓；名次不变不强制交易。止损与抵押品每5分钟检查，杠杆仍每日评估。',
            source='short-term-research/selection-12h-v3/cadence_engine.py · protocol.json',
            boundaries=card['boundaries']+'新增10个12小时版本×6场景，仅改变决策频率；原小时与周度对照保留，未搜索其他频率。')
        CARDS.append(new)


for card in list(CARDS):
    if card['id'].startswith(('academic_control_12h_','academic_combined_12h_')):
        new=deepcopy(card)
        new.update(id=card['id'].replace('_12h_','_event_'),title=card['title'].replace('每12小时','卖出后补位'),
            idea='两个仓位独立；卖出一个仓位后，才从最新已知排名中选择最高合格币补位。',
            entry='初始空位按排名建仓；基础仓卖出后，下一个可执行5分钟时点从最新已结束小时排行榜依次筛选，跳过已持有、数据无效、冷却未结束及入场条件不满足的币；没有合格币保留现金。'+('额外杠杆仍按原日级条件与2%风险预算评估。' if card['id'].endswith('tiered') else ''),
            exit='基础仓只因4%价格止损或UTC00/12点的30日动量方向失效退出，区间末计费平仓。排名下降或离开资格池不直接卖出；持仓自身动量连续计算。额外仓仍按各自止损、日级降档及账户回撤规则退出。',
            cadence='补位发生在卖出后或仍有空位时的可执行5分钟点；只读取当时已结束小时排名。方向退出每12小时、止损每5分钟、杠杆每日；不因定时重排而卖出。',
            source='short-term-research/selection-event-v4/event_engine.py · event_execution.py · protocol.json',
            boundaries='本轮原动量/四因子各1×与动态5×，4版本×6场景。补齐所有潜在补位候选的执行数据；同数据同成本复现原12小时对照。因果数据隔离与持仓缺失中止保留。历史已被研究，未改当前模拟。')
        CARDS.append(new)


add('MinuteIntradayV1','分钟突破 · 全池多空 · 1×研究版',
    '高流动性币池中寻找短线强弱，分钟突破入场，仓位退出后按排名补位。',
    {
      'universe':'历史全池USDT现货资格筛选，映射同币USDT永续；同时允许做多和做空。',
      'pool':'至少90个连续有效日、30日成交额中位数≥1000万USDT、流动性前20；每小时以6小时收益/24小时波动率选正值前三和负值后三。发现数据缺口后才隔离，保留此前历史。',
      'entry':'15分钟EMA20同向，1分钟收盘突破此前20分钟高低点，成交额≥前20分钟中位数1.5倍；目标空间≥基础往返成本3倍。信号后的下一分钟才可成交。',
      'exit':'1.5倍15分钟ATR14止损、2倍止损距离止盈、最多持有60分钟；北京时间22:00停止开仓，23:55清仓。排名变化不强制退出。',
      'allocation':'初始1000USDT；每笔计划损失0.25%、合计≤0.5%；最多2仓，总名义仓位上限1×。上限5×保留为后续研究，当前未启用。',
      'risk':'每天最多6次开仓，同币退出后冷却60分钟。日亏1.5%暂停至次日，回撤5%减半新仓风险，8%平仓并暂停研究路径。',
      'cadence':'每日资格、每小时排名、15分钟方向、1分钟信号与历史撮合。秒级公开行情适配器独立验证，未接实盘。',
      'cost':'基础Taker单边0.05%＋估计滑点单边0.05%，历史资金费率；另测手续费2/3倍、滑点2倍、额外延迟1分钟。',
      'boundaries':'本轮只研究这一套规则，未重跑其他策略。历史已被研究；一分钟OHLC不证明秒级成交。原DailyMomentum模拟不变。',
      'engine':'独立分钟事件回测＋公开WebSocket观察',
      'source':'short-term-research/minute-intraday-v1/protocol.json · engine.py · seconds_observer.py'
    },status='当前重点研究 · 未替换原模拟',link='/minute-research',link_label='查看分钟策略与验证结果')


def catalog():
    return {'version': '2026-11-13', 'configured_strategy': 'DailyMomentum', 'cards': CARDS,
            'counts': {group: sum(c['group'] == group for c in CARDS)
                       for group in ('main', 'control', 'diagnostic')}}
