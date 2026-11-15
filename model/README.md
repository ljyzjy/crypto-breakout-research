# Binance 现货量化实操包：SpotTrendV1

版本日期：2026-11-12。适用：Windows、Binance 现货、只做多、不加杠杆。

这是一个可审查的研究基线及部署流程，不包含已证实盈利的承诺。实际安装、数据和运行结果见 `VALIDATION.md`；以该文件区分已完成与待完成事项。

**本次已跑完回测：SpotTrendV1 未通过真钱启用门槛。系统可用于研究和模拟，当前规则不建议实盘。具体数字见 `BACKTEST_RESULTS.md`。**

**后续比较已完成：** 新增四种慢速现货候选及固定参数邻域测试。结果、早期冻结顺序和完整日志保存在 `comparison-v2/`。优先前瞻模拟候选为 `DailyMomentum`，但盈利集中度和回撤仍需关注；见 `comparison-v2/COMPARISON_REPORT.md`。原默认策略未替换，启动新模拟使用 `run.ps1 paper -Strategy DailyMomentum`，数据库彼此独立。

## 1. 方案结构

Binance 公开月度行情 → 数据校验 → 同一个 Freqtrade 策略 → 历史回测 → 无密钥模拟交易 → 用户自行接入真实账户。

- `user_data/strategies/SpotTrendV1.py`：唯一的策略规则。
- `config.paper.json`：1,000 USDT 虚拟资金，100 USDT/笔，最多两笔。
- `config.public-data.json`：Binance 官方纯行情域名；只用于研究、模拟，不可用于下单。
- `run.ps1`：策略验证、行情下载、回测、前视检查、递归检查、模拟启动。
- `download_archive.py`：从 Binance 官方档案下载月度数据，核对 SHA256，输出 CSV/Feather。
- `config.live.example.json`：实盘配置模板，仍保留 `dry_run: true`，默认不执行实盘。
- `verify_strategy.py`：时间一致性测试，不是收益测试。

Freqtrade 固定为 2026.10。不要在有持仓时随意升级程序或替换策略。

## 2. 明确的交易规则

交易对固定为 BTC/USDT、ETH/USDT，周期 1 小时。使用已收盘 K 线计算信号，回测通常在下一根 K 线开盘成交。

入场同时满足：

1. 50 小时简单移动平均线高于 200 小时简单移动平均线。
2. 本根收盘价高于此前 20 根 K 线最高价；阈值用 `shift(1)` 排除当前 K 线。
3. 本根成交量大于零。

退出满足任一条件：

- 收盘价跌破此前 10 根 K 线最低价。
- 50 小时均线低于 200 小时均线。
- 触发相对开仓价格约 4% 的固定止损。

无做空、无杠杆、无补仓、无马丁、无自动加码；不设固定止盈，以退出信号结束趋势持仓。

每次平仓后该交易对暂停入场 6 根小时 K 线。过去 48 根 K 线中累计两次亏损止损后，全交易对暂停入场 24 根 K 线。保护只阻止新开仓，不会主动清空现有持仓；回测命令已开启 `--enable-protections`。

1,000 USDT、100 USDT/笔仅是研究配置，不是要求投入的金额。初始名义持仓上限为 200 USDT，即初始虚拟资金的 20%；价格上涨后市值可超过该比例。两笔同时在 -4% 平仓的粗略损失为 8 USDT，尚未计手续费、跳空和滑点，不是损失上限。

## 3. 当前网络条件

本次检查中，`api.binance.com/api/v3/time` 返回所在地受限；官方纯行情接口 `data-api.binance.vision` 与历史档案站可访问。

公开行情能下载并不证明账户可交易。这个包通过官方只读行情服务进行研究和模拟，没有改变交易账户所在地或绕过交易权限。实盘之前须由用户确认账户及实际所在地可用 Binance，并确认标准交易 API 能正常使用；如果交易服务仍返回限制，实盘阶段停止。

所有 API Key、Secret 由用户在自己设备上填写，勿发给聊天助手。实盘只授予必要的读取和现货交易权限，关闭提现权限；配置文件不要上传或分享。

## 4. Windows 安装和启动

在 PowerShell 切换到本目录：

```powershell
Set-Location 'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\crypto-spot-kit'
.\setup.ps1
.\run.ps1 version
.\run.ps1 validate
```

安装脚本使用 uv 创建独立 Python 3.12 环境，不更改系统 Python。若已有本次创建的 `../../work/freqtrade-env`，`run.ps1` 会自动使用它。离开当前文件夹迁移到其他电脑时重新运行 `setup.ps1`。

本机现在已安装成功，可以跳过 `setup.ps1`。本次官方包文件下载曾超时，最后使用清华 PyPI 镜像成功安装；如重新安装遇到同类问题，可在环境创建后执行 `uv pip install --python .venv/Scripts/python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.lock.txt`。

如 PowerShell 阻止脚本，只对本次进程执行 `Set-ExecutionPolicy -Scope Process Bypass`，关闭窗口后失效。网络下载失败应保留错误日志，不能据此认为已安装。

下文 Python 命令假定运行了 setup；当前会话可将 `.\.venv\Scripts\python.exe` 替换为 `..\..\work\freqtrade-env\Scripts\python.exe`。

## 5. 下载历史数据

建议用官方月度档案，所有时间为 UTC，结束月份不包含在内：

```powershell
.\.venv\Scripts\python.exe .\download_archive.py --start 2022-10 --end 2026-11 --timeframe 1h
```

下载 BTC、ETH 两个交易对，保留原始 ZIP 和官方 SHA256 校验文件。2025 年起现货档案时间戳变为微秒，下载器已分辨并转换为 UTC。逐月合并后核验重复日期、缺口、OHLC 合法性和非负成交量，发现问题会中止。

本次已发现并核对：两交易对的原始文件均缺少 2023-03-24 13:00 UTC 小时 K 线。默认下载器会因此停止。检查后可加 `--allow-gaps` 保存原始缺口并写入 manifest；Freqtrade 加载时会以前收盘价、零成交量补齐该小时，本策略在零成交量处不生成新信号。该合成占位仍会进入滚动指标，因此开发期存在这项数据限制。2024 年以后本次数据无该缺口。

若已下载原始 ZIP，再次运行优先使用校验过的缓存。CSV 可直接查看，Feather 供 Freqtrade 使用。不要用短日期范围覆盖长期 Feather，若要缩小回测日期，改变回测 `Timerange`。

交付目录已包含下载、验证及转换后的历史数据，无需先重复下载即可回测。

也可用 Freqtrade 的公开行情下载器：

```powershell
.\run.ps1 download -Timerange 20221001-20261101
```

准备细粒度成交检验时，单独下载同一区间的 5 分钟数据：

```powershell
.\.venv\Scripts\python.exe .\download_archive.py --start 2022-10 --end 2026-11 --timeframe 5m
```

## 6. 固定研究方案与回测命令

事先约定：2023 年是开发区间，2024 年是验证区间，2025-01-01 至 2026-11-01 是评估区间（结束日不包含）。2022 年数据提供均线预热。历史上已发生的数据不能称为真正前瞻的盲测；模拟交易才提供新的时间外观测。

`run.ps1` 将日期形式的结束边界转为前一秒的时间戳，因为 Freqtrade 原生筛选包含结束时间，防止相邻研究区间重叠。

```powershell
.\run.ps1 backtest -Timerange 20230101-20240101 -Fee 0.001
.\run.ps1 backtest -Timerange 20240101-20250101 -Fee 0.001
.\run.ps1 backtest -Timerange 20250101-20261101 -Fee 0.001
.\run.ps1 backtest -Timerange 20250101-20261101 -Fee 0.002
.\run.ps1 backtest -Timerange 20250101-20261101 -Fee 0.003
```

`Fee` 是**每边费率**，0.001 表示买卖各 0.1%，不是 Binance 对你账户费率的断言。实际费率由账户等级、交易对和折扣决定。0.002/0.003 是更高交易摩擦的敏感性情景，不能声称精确模拟了盘口滑点。

下载 5 分钟数据后，至少对最终评估区间再运行：

```powershell
.\run.ps1 backtest -Timerange 20250101-20261101 -Fee 0.001 -Detail
```

`--timeframe-detail 5m` 改善小时内止损等路径的模拟，但不能还原逐笔盘口、队列和真实成交。每次回测禁用缓存并导出交易，输出位于 `user_data/backtest_results`。保留失败/负收益结果，不只保留最好的一次。

本次已包含 2024-12 至 2026-10 的 5 分钟数据，足以直接运行上面的评估期细化命令。回测后执行 `.\.venv\Scripts\python.exe .\summarize_results.py` 可更新 Markdown/CSV 汇总（当前环境路径替换同上）。

验证信号使用的信息范围：

```powershell
.\.venv\Scripts\python.exe .\verify_strategy.py
.\run.ps1 lookahead -Timerange 20230101-20261101
.\run.ps1 recursive -Timerange 20250101-20261101
```

合成测试检查未来价格变化不会改变过去信号；Freqtrade 的 lookahead 检查补充基于历史交易的切片比较。若没有足够交易而跳过分析，不能记录为“通过”。本策略用有限窗口 SMA，预热 210 根应覆盖指标，但仍保留递归检查。

## 7. 如何判断是否值得继续

记录每个区间的净收益、最大回撤、交易数、胜率、盈亏比、Profit Factor、平均持仓时间、最差月份、单币贡献及费用。净收益使用包含闲置现金的完整 1,000 USDT 账户口径。

基准至少有两个：全现金，以及期初各买入 100 USDT BTC/ETH 并保留 800 USDT 现金的买入持有组合。另列满仓买入持有时，须注明资金暴露不同。最大回撤应基于含未实现盈亏的权益曲线，不用累计已平仓利润替代。

进入模拟阶段的研究门槛建议：数据及时间检查通过；独立评估期基础费用和双倍费用下的扣费收益均为正；最大账户回撤不超过事先设定的 10%；总交易数达到约 100 笔，否则承认样本不足；收益不由某一个交易对或单个月份包办。这些是筛选门槛，不是盈利保证，也不是统计显著性检验。

若门槛未满足，只能将模拟用于技术验收，不进入真钱交易。若调整规则，要更新版本并重新标注评估区间，不能继续称已反复看过的数据为独立测试。

## 8. 模拟交易与日常运行

```powershell
.\run.ps1 paper
```

该命令使用公开盘口/行情和模拟钱包，不需要 API Key，也不会向交易所发送真实订单。进程需持续运行；Ctrl+C 可停止，睡眠、断网和关机会中断运行。保持电脑联网并关闭自动睡眠，不要同时启动两个实例。

另一窗口查看日志：

```powershell
Get-Content .\user_data\logs\paper.log -Tail 40 -Wait
```

数据库为 `user_data/paper.sqlite`，重启沿用同一数据库。不要删除数据库来“重置亏损”。本包未开放远程网页面板，避免额外服务配置；不需要云服务器即可开始。

建议至少观察 2–4 周，且收集足够完整交易；低频时应延长。每天核对最新行情、程序心跳、虚拟持仓、下单/退出事件、滑点与费用、断网恢复。没有信号和没有交易并不一定是故障。

## 9. 用户自行切换实盘的操作路线

实盘条件：策略通过研究门槛；模拟完整运行；账户及所在地可使用交易服务；最小下单额和精度可满足；确认资金规模与可接受损失。

1. 使用单独账户或可用的独立子账户，不混入其他手动仓位或其他机器人。API Key 仅在本机保存，不启用提现。
2. 复制 `config.live.example.json` 为 `config.live.local.json`，由用户在本地编辑器填写 `exchange.key`、`exchange.secret`。本包没有任何真实凭据。
3. 从小额单交易对验证开始：模板为 20 USDT/笔、最多一笔 BTC/USDT，须核对当时最小订单与自身预算。这个金额仅用于展示配置方式。
4. 仍保留 `dry_run: true`，先用标准 Binance 域名运行最终配置进行连接检查；不要加载 `config.public-data.json`，也不要使用只支持模拟的 `run.ps1` 实盘。
5. 全部满足后，由用户将本地实盘文件改为 `dry_run: false`，确认进程环境不存在覆盖配置的 `FREQTRADE__DRY_RUN` 等变量，并亲自执行下方命令。该命令可能产生真实订单。

```powershell
# 仅由用户完成上述检查、填写本地文件后执行。
.\.venv\Scripts\python.exe -m freqtrade trade --config config.paper.json --config config.live.local.json --userdir user_data --logfile user_data/logs/live.log
```

本地实盘文件覆盖基础模拟配置；实盘数据库独立为 `user_data/live.sqlite`。启动日志必须明确显示实际 dry-run 状态，不能仅凭文件名判断。

模板为 Binance 现货启用交易所端限价止损。触发价约为开仓价下方 4%，止损限价比例 0.99；例如触发价 96，挂单限价约 95.04。急跌时限价止损可能不成交，4% 不构成损失保证。必须在真实账户自行核对止损订单确实已创建。

停止程序通常不会自动卖出现货。发生异常时：停止新入场，用户到交易所核对未成交订单与持仓，按预定风险方案处理；不要盲目删除数据库或另启一个实例。任何真实平仓、取消订单与资金划转均由用户操作。

## 10. 运维规则

- 每天核对账户与机器人持仓一致、交易所端止损存在、日志无持续失败；不要只看是否盈利。
- 明确人工停止条件：例如账户相对启用时的权益回撤达 5%，或订单/持仓不一致、行情长期不更新时，停止开新仓并检查。这是人工运维规则，本策略未实现自动账户级 5% 熔断。
- 防护项里的连续止损暂停不能替代账户权益风控，也不能处理交易所故障。
- 模拟完成前不购买 VPS；需要长期无人值守时再部署。迁移须携带正确数据库，先停旧实例，再启动新实例，避免重复下单。
- 记录策略、配置、依赖与数据版本，升级先在独立模拟环境验证。

## 11. 官方资料

- Freqtrade 回测：https://www.freqtrade.io/en/stable/backtesting/
- 策略编写：https://www.freqtrade.io/en/stable/strategy-customization/
- 模拟和实盘配置：https://www.freqtrade.io/en/stable/configuration/
- 交易所差异：https://www.freqtrade.io/en/stable/exchanges/
- 止损：https://www.freqtrade.io/en/stable/stoploss/
- 前视检查：https://www.freqtrade.io/en/stable/lookahead-analysis/
- Binance 公开行情：https://developers.binance.com/en/docs/products/spot/faqs/market_data_only
- Binance 历史档案与时间戳说明：https://github.com/binance/binance-public-data
