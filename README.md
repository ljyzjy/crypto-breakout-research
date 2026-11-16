# Digital Asset Models and Breakout Strategy Research

This repository contains a source snapshot of the original Freqtrade model and subsequent research on 15-minute breakouts. The research evaluates second-level entries, exit methods, trading fees, slippage, funding rates, and risks under 10x and 20x leverage.

**Research status (November 15, 2026):** The breakout rules tested so far have not met all project targets for net win rate, profitability after trading costs, and account risk. Historical results do not guarantee future performance, and this repository is not an instruction to enable live trading.

## Contents

- [`model/`](model/) contains the original `crypto-spot-kit` strategies, dashboard, and run scripts. Related historical research code and reports are in `model/research-history/`. The original model includes spot and slower-timeframe strategies; the breakout research has not been automatically integrated into its live or paper accounts.
- [`research/`](research/) contains code, reports, and lightweight summaries covering breakout integration, leverage, execution costs, and ongoing optimization. See the [latest research record](research/%E7%AA%81%E7%A0%B4%E7%9B%88%E5%88%A9%E6%8C%81%E7%BB%AD%E4%BC%98%E5%8C%96_v1/%E6%9C%80%E6%96%B0%E7%BB%93%E6%9E%9C%E4%B8%8E%E7%BB%A7%E7%BB%AD%E8%BF%90%E8%A1%8C.md) and the [first-second directional flow and trailing-exit study](research/%E7%AA%81%E7%A0%B4%E7%9B%88%E5%88%A9%E6%8C%81%E7%BB%AD%E4%BC%98%E5%8C%96_v1/%E7%AC%AC%E4%B8%80%E7%99%BE%E4%B8%80%E5%8D%81%E5%9B%9B%E8%BD%AE_%E5%BC%BA%E6%96%B9%E5%90%91%E6%88%90%E4%BA%A4%E4%B8%8E%E8%B7%9F%E8%B8%AA%E7%BB%84%E5%90%88/%E5%BC%BA%E6%96%B9%E5%90%91%E6%88%90%E4%BA%A4%E4%B8%8E%E8%B7%9F%E8%B8%AA%E9%80%80%E5%87%BA%E7%BB%93%E6%9E%9C.md). These historical reports are in Chinese.
- [`data/`](data/) documents the public market inputs and the original data release. The [BTC trend research input package](data/btc-trend-v4-2026/) adds the prepared 2026 backtest inputs and selected source data.
- [`project-inventory.json`](project-inventory.json) records the hashes of the original packaged source snapshot. Files changed after that snapshot and later additions, including the data-release files, are not covered by those original hashes.

## Data and Configuration

Selected backtest summaries and simulated trade records are included in the repository. The earlier large public market archives are distributed through a data release; they are not part of a normal clone. The smaller [BTC trend input package](data/btc-trend-v4-2026/) is included in the repository. Runtime environments, caches, live and paper account databases, logs, and machine-specific configuration files are excluded. Keys, passwords, tokens, and similar fields have been cleared from the packaged model configurations. The local API server and messaging notifications are disabled, and every configuration containing `dry_run` has it set to `true`. The initial packaging did not modify the source computer; subsequent strategy changes are described below.

Some historical scripts, frozen snapshots, and reports retain absolute paths from the original computer and depend on market data, checkpoints, or other local files. The data release covers selected inputs; reproducing historical backtests can require additional files, processing, validation, and path changes. The original model documentation is preserved as a historical record; statements that data has already been downloaded refer to the source computer, not a new clone.

One [round 43 study plan](research/%E7%AA%81%E7%A0%B4%E7%9B%88%E5%88%A9%E6%8C%81%E7%BB%AD%E4%BC%98%E5%8C%96_v1/%E7%AC%AC%E5%9B%9B%E5%8D%81%E4%B8%89%E8%BD%AE_%E6%97%A7%E5%8D%81%E4%B8%80%E5%B8%812023%E5%B9%B4%E5%A4%8D%E6%A0%B8/%E9%80%90%E7%AC%94%E6%89%A7%E8%A1%8C%E5%86%BB%E7%BB%93%E6%96%B9%E6%A1%88.json) is Markdown text with a `.json` extension in the original research. Its name and contents are preserved for historical references and hash checks.

## Local Use

The base model dependency lockfile is [`model/requirements.lock.txt`](model/requirements.lock.txt). The [original model instructions](model/README.md) are in Chinese. Before running any strategy, review its configuration, data sources, and the availability of the trading service in your region. If an account connection is needed, create the configuration locally.

The daily BTC perpetual trend strategy [`BtcTrendV4`](model/user_data/strategies/BtcTrendV4.py) has position adjustment enabled and uses stake units for rebalancing. It blocks new short entries when the daily funding file is missing or the required value is unavailable. By default it keeps the original zero-crossing exit; set `EXIT_WHEN_TARGET_ZERO` to `True` to evaluate the alternative target-zero exit, which also exits an existing short when the funding gate closes. These changes affect this daily trend strategy and do not change the separate 15-minute breakout research. The strategy requires a local `model/user_data/funding_daily.csv` and sufficient market history. Its wallet accounting, fills, funding and exit rules can differ from the historical research simulator; a successful signal check alone does not validate live execution or profitability.

The following lightweight synthetic checks test breakout exit rules and BTC trend sizing and funding handling; they do not establish profitability or actual execution. Run them from the repository root:

```powershell
python -c "from pathlib import Path; import subprocess,sys; p=next(Path('research').rglob('test_oracle_exit.py')); subprocess.run([sys.executable,str(p)],check=True)"
python -c "from pathlib import Path; import subprocess,sys; p=next(Path('research').rglob('test_trailing.py')); subprocess.run([sys.executable,str(p)],check=True)"
python -m unittest -v model.tests.test_btc_trend_v4
```

These checks write synthetic verification files next to the corresponding scripts. Funding, liquidation, actual market-order execution, and unrealized account equity still require separate validation.

