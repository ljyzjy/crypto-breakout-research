# 比较结果及新策略的运行入口

先读 COMPARISON_REPORT.md 和 VALIDATION.md。本轮优先模拟候选为 DailyMomentum（30日动量）；收益集中、样本量及地区接口限制尚未消除，不自动切换实盘。

所有文件已写入原项目目录。无需重新安装环境、无需下载新行情。原 SpotTrendV1 保留为默认策略；没有启动新的模拟或实盘后台。

## 单策略复现

```powershell
Set-Location 'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\crypto-spot-kit'
.\run.ps1 backtest -Strategy DailyMomentum -Timerange 20250101-20261101 -Fee 0.001
.\run.ps1 backtest -Strategy DailyMomentum -Timerange 20250101-20261101 -Fee 0.002
.\run.ps1 backtest -Strategy DailyMomentum -Timerange 20250101-20261101 -Fee 0.001 -Detail
```

其他候选的 `-Strategy` 可取 `DailyDonchian`、`DailyMA`、`DailyBollinger`，原策略为 `SpotTrendV1`。不要从诊断变体中选最高收益版本上线。

## 用户自行启动模拟

```powershell
.\run.ps1 paper -Strategy DailyMomentum
```

保持电脑联网、不休眠。Ctrl+C 停止。此命令强制使用 dry-run，不需要密钥，不下真实订单。

新模拟数据库为 `user_data/paper-DailyMomentum.sqlite`，不与原策略数据库混用。日志为 `user_data/logs/paper-DailyMomentum.log`，可用 `Get-Content` 追踪。

完整规则：每个 UTC 日结束后，用当日收盘价除以30天前收盘价，收益大于0时允许持多，小于等于0时退出；实际订单在下一小时处理。沿用每笔100 USDT、最多两笔、4%止损及共同保护。北京时间对应日线收盘是次日08:00；美国东部本地时间随夏令时变化。算法统一按UTC计算。

先安排4–8周技术观察，检查信号、成交模拟、断网恢复和持仓一致性。盈利稳定性还需更多完整交易；本次历史频率平均每月约3笔，积累20–30笔可能需要数月，不能把几周无故障当成盈利验证。

## 全批次复核

```powershell
..\..\work\freqtrade-env\Scripts\python.exe .\comparison-v2\verify_candidates.py
..\..\work\freqtrade-env\Scripts\python.exe .\comparison-v2\run_comparison.py selection
..\..\work\freqtrade-env\Scripts\python.exe .\comparison-v2\run_comparison.py evaluation
..\..\work\freqtrade-env\Scripts\python.exe .\comparison-v2\build_report.py
```

分阶段脚本会校验原协议、策略、配置和数据哈希。已有完整结果则复用；需要研究新规则时另建实验版本，不覆盖已冻结的候选顺序。若要强制重新执行原条件，可复制项目并在新副本中单独保存新的 results 目录；不要修改原始证据。

全部正式数值见 all_metrics.csv，原生引擎 ZIP 包含策略、配置与交易明细。报告中的权益回撤由钱包市值重算，可能高于引擎只展示已平仓交易的默认摘要。
