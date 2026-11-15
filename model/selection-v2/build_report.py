"""Presentation only: reads frozen outcomes, never changes parameters or reruns trades."""
import collections,gzip,html,json
from pathlib import Path
import pandas as pd
from study import LABELS,P,ROOT,fingerprint

rows=json.loads((ROOT/'metrics.json').read_text(encoding='utf-8'))
lookup={(r['window'],r['mode'],r['fee'],r['extra_lag']):r for r in rows}
def get(mode,window='later',fee=.001,lag=0):return lookup[(window,mode,fee,lag)]
def load(mode,window='later'):
    with gzip.open(ROOT/'results'/f'{window}-{mode}-0.001-lag0.json.gz','rt',encoding='utf-8') as f:return json.load(f)
def fmt(x):return f'{x:.2f}'
base,old=get('baseline'),get('selection')
pair_rows=[]
for coin in sorted(set(base['pair_pnl'])|set(old['pair_pnl'])):
    b=base['pair_pnl'].get(coin,0);o=old['pair_pnl'].get(coin,0)
    pair_rows.append({'symbol':coin,'baseline_pnl':b,'v1_pnl':o,'v1_minus_baseline':o-b})
pd.DataFrame(pair_rows).to_csv(ROOT/'coin_attribution.csv',index=False,encoding='utf-8-sig')
episodes=json.loads((ROOT/'eth_episodes.json').read_text())
top=sorted(episodes,key=lambda e:-e['pnl'])[:3]

lines=['选币策略为何落后，以及固定方案比较',
       '结论：保留当前 DailyMomentum 模拟策略；本轮三种新候选均缺少替换依据。',
       '', '一、研究范围与公平比较',
       '完全复用 selection-v1 冻结的 20 币日线数据和 2022 年末形成的研究范围。没有下载新数据、加入新币或按当前存活状态删币。',
       '账户初始 1000 USDT，总目标仓位上限 20%，无杠杆。每日只读取上一日及更早数据；次日开盘模拟成交。统一 4% 保护止损、2 天冷却、10 USDT 最小模拟买单。',
       '基础费用单边 0.1%，另加单边 0.05% 不利滑点；压力费用为单边 0.2% 和 0.3%，滑点不变。保留日线内成交近似和实际仓位漂移的限制。',
       '本轮 BTC/ETH 对照是日线研究版，不是现有 Freqtrade 小时实跑的精确复刻。比较只在同一日线引擎内进行。',
       '先冻结 3 个新候选和 5 个单因素诊断，另有 2 个原有对照；60 个主要/诊断场景加10个事先固定的一日额外信息滞后压力场景，共70个。没有按结果扩展方案或搜索参数。',
       '2023–2024 与 2025–2026 均已被观察过，后段不能称为完全未见的样本外样本。分年运行各自重置，不能直接相加得到连续区间。',
       '', '二、V1 落后的账面来源（2025-01-01 至 2026-10-31）',
       f"BTC/ETH 对照收益 {fmt(base['return_pct'])}%，V1 {fmt(old['return_pct'])}%，差 {fmt(base['return_pct']-old['return_pct'])} 个百分点，即 {fmt((base['return_pct']-old['return_pct'])*10)} USDT。",
       f"ETH 净贡献由对照的 {fmt(base['pair_pnl']['ETHUSDT'])} USDT 降到 V1 的 {fmt(old['pair_pnl']['ETHUSDT'])} USDT，减少 {fmt(base['pair_pnl']['ETHUSDT']-old['pair_pnl']['ETHUSDT'])} USDT，几乎解释全部收益差距；其他币的合计差异略有抵消。",
       f"对照平均实际仓位 {fmt(base['mean_exposure']*100)}%，V1 为 {fmt(old['mean_exposure']*100)}%；完全空仓分别 {base['cash_days']} 和 {old['cash_days']} 天，共 {base['days']} 天。V1 BTC大盘过滤关闭 {old['gate_off_days']} 天。现金占用和低波动率排序叠加限制了趋势参与，但这些统计本身不是因果分解。",
       f"手续费：对照 {fmt(base['fees'])}，V1 {fmt(old['fees'])} USDT；滑点支出：对照 {fmt(base['slippage_cost'])}，V1 {fmt(old['slippage_cost'])}。因此不能说 V1 因为手续费总额更高而落后。",
       f"按同一组已发生的模拟成交，回加费用和滑点后的毛盈亏：对照 {fmt(base['fixed_fill_gross_pnl'])}、V1 {fmt(old['fixed_fill_gross_pnl'])} USDT。V1 的毛优势本来就弱，{fmt(old['fees']+old['slippage_cost'])} USDT 的成本进一步吞噬它。该回加是账面分解，不是重新按零成本交易。",
       f"V1 有 {old['exit_reasons']['intraday_stop']['fills']} 次日内止损成交，合计净盈亏 {fmt(old['exit_reasons']['intraday_stop']['pnl'])} USDT；对照为 {base['exit_reasons']['intraday_stop']['fills']} 次、{fmt(base['exit_reasons']['intraday_stop']['pnl'])} USDT。V1 在更低平均敞口下承受了相近绝对止损损失。成交数包含仓位操作，不能视为独立统计样本。",
       '', '三、不是每一段盈利都被大盘过滤挡住',
       '以下按对照最大 ETH 盈利成交事后定位，仅用于解释已有结果，不作为交易信号：']
for e in top:
    lines.append(f"{e['entry']} → {e['exit']}：对照净盈利 {fmt(e['pnl'])} USDT；该区间 V1 大盘过滤关闭 {e['v1_gate_off']}/{e['days']} 天，ETH 正目标权重 {e['v1_eth_target_days']}/{e['days']} 天；对照入场日的 V1 个币MA100条件 {'通过' if e['entry_above_ma100'] else '不通过'}。")
lines+=['2025年7月至9月的大盈利段，V1几乎一直给ETH正目标，但仍不能复制对照收益。原因同时涉及入场日、较小仓位、周度减仓/补仓及补仓抬高止损，不能只归因于没买到。',
        '', '四、单因素诊断：每次仅改变 V1 的一个操作',
        '场景 | 2023–2024收益 | 2025–2026收益 | 后段回撤 | 后段相对原V1收益差']
for mode in ['selection']+P['diagnostic_variants']:
    a,b=get(mode,'early'),get(mode)
    lines.append(f"{LABELS[mode]} | {fmt(a['return_pct'])}% | {fmt(b['return_pct'])}% | {fmt(b['max_drawdown'])}% | {fmt(b['return_pct']-old['return_pct'])}个百分点")
lines+=['诊断支持大盘过滤、权重和再平衡各有影响，但没有任何单项消融追上对照。去掉个币MA100、每日补空缺在后段反而更差，不支持一味取消过滤。',
        '关闭再平衡同时取消加仓引起的止损上移，这是关闭该操作的实际后果，不能解读成纯粹“少付手续费”的实验。',
        '单因素结果有交互，不能相加，更不能把其中较好的修改拼成未经事先定义的新赢家。本轮未运行这种事后组合。',
        '', '五、只比较三个预先固定的新结构',
        'A 流动性四币等权：周度流动性筛选，最多4币，每币预留5%；各自30日动量择时，允许每日入场；空出的仓位留现金，不重分配、不调整已有仓位。',
        'B 四币相对动量：原有流动性币池内，周度按30日动量选最多4币；已有成员排名前6可保留，每币5%；每日检查动量退出，已有仓位不再平衡。',
        'C 核心＋单卫星：BTC/ETH各预留7.5%，各自30日动量择时；剩余5%最多选择一个流动性合格、动量领先的卫星币，已有卫星排名前2可保留。卫星名额空缺不加到核心。',
        '三者都删除V1的MA200大盘总开关和个币MA100冗余条件；降低复杂度只是可解释性假设，不保证更高收益。',
        '', '方案 | 早段收益 | 后段收益 | 后段回撤 | 后段双倍费用收益 | 后段三倍费用收益 | 后段平均仓位']
for mode in P['main_variants']:
    a,b=get(mode,'early'),get(mode)
    lines.append(f"{LABELS[mode]} | {fmt(a['return_pct'])}% | {fmt(b['return_pct'])}% | {fmt(b['max_drawdown'])}% | {fmt(get(mode,fee=.002)['return_pct'])}% | {fmt(get(mode,fee=.003)['return_pct'])}% | {fmt(b['mean_exposure']*100)}%")
lines+=['', '六、年度与额外信息延迟敏感性', '方案 | 2023 | 2024 | 2025 | 2026年1–10月 | 后段额外滞后一日收益']
for mode in P['main_variants']:
    lines.append(LABELS[mode]+' | '+' | '.join(fmt(get(mode,y)['return_pct'])+'%' for y in ['2023','2024','2025','2026'])+' | '+fmt(get(mode,lag=1)['return_pct'])+'%')
lines+=['额外滞后一日是交易时仅用两天前数据的固定压力场景，不是精确模拟已提交订单晚一天成交。某些候选由负转正，提示结果对时点敏感，不能挑压力场景里较好的版本替代原方案。',
        '', '七、核心＋卫星为何也没赢']
c=get('core_satellite');core=sum(c['pair_pnl'].get(s,0) for s in ['BTCUSDT','ETHUSDT']);sat=sum(c['pair_pnl'].values())-core
lines +=[f"后段核心 BTC/ETH 净贡献 {fmt(core)} USDT，卫星合计 {fmt(sat)} USDT，总收益 {fmt(c['return_pct'])}%。相比基线，核心预留资金从20%降至15%，卫星部分又净亏损。该结构没有提供足够的额外分散收益，且后段回撤更大。",
         '这是持仓贡献的账面解释，各仓位受账户资金变化影响，不能把差额解释为互相独立的因果效应。',
         '', '八、信息边界与核验',
         '两个原策略在早段/后段重新运行，决策、订单和收益/回撤/仓位与冻结V1精确对齐。',
         '10种规则均通过合成数据的截断、当日/未来价格成交量扰动、仓位上限、现金非负和账本核对。',
         '真实数据对10种规则各在2023-06-30、2024-06-30、2025-06-30三个截点做决策及订单前缀检查，另做未来数据放大100倍检查；全部通过。',
         '70个场景全部保存。形成日限制、退市/断流标记仍保留；本批场景没有持仓缺失价格事件。研究代码、协议和20币数据哈希在结果计算前后保持一致。',
         '数据修订、归档遗漏、固定2022年末名单未覆盖后续新币，以及日内路径/历史交易精度近似仍无法由这些测试排除。没有用通过检查来声称已证明实盘有效。',
         '', '九、行动结论',
         '当前模拟策略保持原样，不重启进程、不改配置、不重置数据库、不启用新候选。',
         '本轮不推荐从3个新方案中强行选一个替换现状。核心＋卫星的结构较容易解释，但已有后段证据不支持把卫星仓位加进当前模拟账户。',
         '当前对照的盈利也高度依赖ETH的少数趋势，继续前瞻记录信号、成交与风险比重复挑选历史参数更有价值。若未来扩大新币覆盖或检验波动率止损，应先形成独立的新研究协议，不能把它们事后追加成本轮成功版本。',
         '', '研究依据与复核入口',
         '动量研究支持研究这类信号，但不证明这里的30日窗口、20币名单或分仓比例有效：',
         'Liu & Tsyvinski, Risks and Returns of Cryptocurrency: https://www.nber.org/papers/w24877',
         'Liu, Tsyvinski & Wu, Common Risk Factors in Cryptocurrency: https://www.nber.org/papers/w25882',
         '协议：protocol.json；冻结哈希：frozen.json；全部指标：metrics.csv / metrics.json；原始路径：results/*.json.gz。',
         '测试：test_study.py；真实数据检查加 --real；原策略精确复现：reconciliation.json；真实检查结果：causality.json。',
         '复现已有完整结果：使用原有 work/freqtrade-env/Scripts/python.exe 执行本目录 reproduce.py，已存在场景读取缓存。']
(ROOT/'研究结论.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def tab(headers,body):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in body)+'</tbody></table></div>'
diagnostic=tab(['单项修改','早段收益','后段收益','后段回撤'],[[LABELS[m],fmt(get(m,'early')['return_pct'])+'%',fmt(get(m)['return_pct'])+'%',fmt(get(m)['max_drawdown'])+'%'] for m in ['selection']+P['diagnostic_variants']])
attribution=tab(['币种','BTC/ETH对照净贡献','V1净贡献','V1减对照 / USDT'],[[r['symbol'],fmt(r['baseline_pnl']),fmt(r['v1_pnl']),fmt(r['v1_minus_baseline'])] for r in pair_rows])
rules=tab(['方案','选币','择时','分仓'],[
['流动性等权','周度流动性前4，已有成员前6可保留','各自30日动量，日更','每币5%，空位留现金，不调整已有仓位'],
['相对动量','流动性币池中周度30日动量前4，已有成员前6可保留','正动量持有，日更退出','每币5%，不调整已有仓位'],
['核心＋单卫星','BTC/ETH核心＋动量领先的单一卫星','核心日更；卫星周选、日更退出','BTC/ETH各7.5%，卫星5%，空位留现金']])
body=''.join('<p>'+html.escape(x)+'</p>' for x in lines)
payload=json.dumps(rows,ensure_ascii=False).replace('</','<\\/')
page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>选币策略诊断与固定方案比较</title><style>
body{margin:0;background:#0c1421;color:#e4edf8;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1200px;margin:auto;padding:38px 28px}h1{font-size:30px;margin-bottom:10px}h2{font-size:21px}p{margin:9px 0}.muted{color:#9cadc3}.card{background:#152033;border:1px solid #2b3b51;border-radius:12px;padding:24px;margin:20px 0}.warning{border-left:5px solid #e5b86b}b{color:#74dfbb}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.grid .card{margin:0}.num{font-size:28px;color:#74dfbb}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{text-align:left;border-bottom:1px solid #2c3b4d;padding:11px 13px}th{color:#a8bbd4}.scroll{overflow:auto}select{background:#0d1828;color:white;border:1px solid #4c6079;border-radius:6px;padding:8px;margin:0 18px 12px 8px}summary{cursor:pointer;color:#74dfbb}details p{font-size:13px}a{color:#74dfbb}.note{font-size:13px;color:#abb9ce}@media(max-width:700px){.grid{grid-template-columns:1fr}main{padding:20px 16px}h1{font-size:24px}}</style></head><body><main>
<p class="muted">本机研究报告 · 原模拟账户未改动 · 2026-11-12</p><h1>选币增加了复杂度，却没有稳定增加收益</h1>
<section class="card warning"><strong>行动结论：保留现有模拟策略。</strong><p>3个预先固定的新方案都没有取得足够的后段证据。没有根据中途结果修改参数、拼接较好的单项修改或隐藏亏损场景。</p></section>
<div class="grid"><div class="card"><div class="muted">V1 后段相对对照少赚</div><div class="num">117.71 USDT</div><p class="note">其中 ETH 净贡献差 118.78 USDT，其他币合计略有抵消。</p></div><div class="card"><div class="muted">V1 平均实际仓位</div><div class="num">4.65%</div><p class="note">对照 10.83%；669 天中，V1 有 440 天完全空仓。</p></div><div class="card"><div class="muted">预定场景 / 因果时序检查</div><div class="num">70 / 全部通过</div><p class="note">仅 3 个新候选；另含单项诊断、费用、年度与信息滞后压力。</p></div></div>
<section class="card"><h2>为什么落后：证据支持哪些解释</h2><p>① <b>ETH盈利段的参与方式改变了。</b>较低权重、额外均线、每周才新开仓、减仓补仓及补仓提高止损共同改变了持有路径。</p><p>② <b>低仓位减少风险，也减少趋势收益。</b>但仅看平均仓位不能作因果解释；逐项诊断没有哪一项能单独填补差距。</p><p>③ <b>不是手续费总额更高。</b>V1 手续费 7.83 USDT，对照 13.22；V1 已发生成交回加费用滑点后的毛盈亏也仅15.22 USDT，对照141.03。</p><p>④ <b>不支持盲目取消过滤。</b>去掉个币MA100或允许每日补空缺，后段反而变差。关闭再平衡的收益改善也包含取消加仓后止损上移的影响。</p>'''+diagnostic+'''<p class="note">单项变化存在交互，不能相加；本轮没有将较好的消融拼成新策略。</p></section>
<section class="card"><h2>三种固定候选，分别检验三种经济逻辑</h2>'''+rules+'''<p class="note">共同上限20%目标仓位，初始1000 USDT，4%止损、2天冷却；不分配的仓位留现金。实际比例允许随价格漂移。</p></section>
<section class="card"><h2>查看全部比较结果</h2><label>区间<select id="window"><option value="later">2025—2026年10月</option><option value="early">2023—2024</option><option value="2023">2023年</option><option value="2024">2024年</option><option value="2025">2025年</option><option value="2026">2026年1—10月</option></select></label><label>单边费用<select id="fee"><option value="0.001">0.1%</option><option value="0.002">0.2%</option><option value="0.003">0.3%</option></select></label><label>信息滞后<select id="lag"><option value="0">上一日已完成数据</option><option value="1">再滞后一日（压力测试）</option></select></label><div id="table"></div><p id="state" class="note"></p><p class="note">所有场景另加单边0.05%不利滑点。年度仅事先规定基础费用和标准滞后，空组合不临时补跑。对照为同一日线研究引擎，不与原网站小时版数字混用。</p></section>
<section class="card"><h2>币种贡献：V1 与对照的账面差异</h2>'''+attribution+'''<p class="note">2025-01-01至2026-10-31，基础费用；贡献是成本后已实现盈亏，不是独立因果效应。</p></section>
<section class="card"><h2>更简单的结构也要接受失败结果</h2><p>流动性等权后段收益−1.37%，相对动量−0.39%；核心＋卫星为4.85%，仍低于对照12.12%，且回撤9.48%高于对照7.49%。核心＋卫星的卫星净贡献约−39.98 USDT。</p><p>三种候选在早段都更好，到后段却退化；2026年已有区间也全部为负。延迟压力会使部分方案由负转正，说明结果对时点敏感，不能挑最好的执行口径。</p><p>核心＋卫星的规则较易解释，但没有证据支持现在启用卫星仓位。当前对照也依赖少数ETH趋势，保留模拟只是继续前瞻观察，不是确认其未来会赢。</p></section>
<section class="card"><h2>无前视检查与剩余限制</h2><p>10种规则都通过真实数据3个截点的历史决策/订单不变检查，以及未来数据放大100倍检查。两个旧策略精确复现，全部资金账本核对，规则与数据哈希未变。</p><p>这些检查不消除归档遗漏、历史修订、固定名单未覆盖新币和日线成交近似。已观察过的2025—2026不能称为全新的样本外证据。没有对当前模拟账户、进程或网页做部署。</p><p class="note">背景依据：<a href="https://www.nber.org/papers/w24877">加密货币时间序列动量研究</a>、<a href="https://www.nber.org/papers/w25882">加密货币共同风险因子研究</a>。论文不证明本报告参数有效。</p></section>
<details class="card"><summary>展开完整研究记录、年度表和复现说明</summary>'''+body+'''</details><p class="note">随报告提供 metrics.csv、coin_attribution.csv、protocol.json、frozen.json、causality.json 及全部70个原始结果。缓存复核不新增参数试验。</p></main>
<script>const rows='''+payload+''';const names=['baseline','selection','liquidity4','relative4','core_satellite'];const $=id=>document.getElementById(id);const fmt=n=>n.toFixed(2);function render(){const w=$('window').value,f=Number($('fee').value),l=Number($('lag').value);const data=rows.filter(r=>r.window===w&&r.fee===f&&r.extra_lag===l&&names.includes(r.mode));$('table').innerHTML=data.length?'<div class="scroll"><table><thead><tr>'+['方案','收益','最大回撤','平均仓位','手续费/USDT','卖出成交笔数'].map(v=>'<th>'+v+'</th>').join('')+'</tr></thead><tbody>'+data.map(r=>'<tr><td>'+r.label+'</td><td>'+fmt(r.return_pct)+'%</td><td>'+fmt(r.max_drawdown)+'%</td><td>'+fmt(r.mean_exposure*100)+'%</td><td>'+fmt(r.fees)+'</td><td>'+r.exit_fills+'</td></tr>').join('')+'</tbody></table></div>':'<p>该组合不在预先固定的试验范围内，未运行。</p>';$('state').textContent=data.length?'显示 '+data.length+' 个原始场景。卖出成交数可能包含减仓，不能视为独立样本。':'年度只跑基础成本；额外信息滞后只在两段连续窗口和基础成本下测试。';}['window','fee','lag'].forEach(id=>$(id).onchange=render);render();</script></body></html>'''
(ROOT/'研究报告.html').write_text(page,encoding='utf-8')
assert len(rows)==70 and all(r['valid_for_comparison'] for r in rows)
assert fingerprint()==json.loads((ROOT/'frozen.json').read_text())['hashes']
print('Report, attribution table and complete conclusions written; 70 valid scenarios; hashes unchanged')
