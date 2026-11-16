# BTCUSDT USD-M hourly data: 2020-01-01 to 2026-11-15

This package contains Binance USD-M BTCUSDT perpetual traded-price and mark-price 1-hour candles. Both series use UTC hour-open timestamps and span **2020-01-01 00:00 through 2026-11-15 23:00 UTC**, inclusive. Each contains 60,264 hourly timestamps with no missing or duplicate hours. On 2026-11-16 UTC, the exchange's 2026-11-16 daily archives were not yet published; this snapshot stops at the latest then-available complete UTC day.

## Downloads

| File | Contents | SHA-256 |
| --- | --- | --- |
| [Prepared data](btc-usdm-hourly-2020-20261115-prepared.zip) | Freqtrade-compatible hourly traded price and mark price, daily traded price derived from hourly data, and the separately labelled reconstructed candidate | `1102cd0e45fad6e958f0fd00ccc93c7c4a864a4c83dd0a72aa998302208e29ce` |
| [Original hourly archives](btc-usdm-hourly-2020-20261115-raw.zip) | 203 official monthly and daily ZIPs with their exchange checksum sidecars | `9c31c5c07909e365da0a5f637c9a32a0dc203d5b41bd5a28f09016fcafa944ba` |
| [Original traded-price fields](BTCUSDT-1h-futures-source-fields-20200101-20261115.csv.gz) | 60,264 hourly rows with all 12 original Binance Kline fields; this file preserves the anomaly described below | `1ce7f7f30620c9885ff1c5128eff48868e3d792296c7d9cbef4b4a550c45e1e5` |

The [quality report](quality-report.json) documents coverage, comparison results, source gaps, anomaly details, and the source links and hashes of the trades used in the independent check. The [source inventory](source-inventory-final.json) lists the hourly archive URLs and checksums. Both ZIP files also include a member-level `SHA256SUMS` manifest.

## Data quality and definitions

* The source is Binance USD-M futures, not spot. Traded price and mark price are different series; mark-price volume is a zero placeholder and must not be interpreted as market volume.
* Nine days (216 hourly records) missing from official mark-price monthly archives were supplied from matching official **daily 1h mark-price** archives. Source checksums were verified. No interpolation was used.
* The prepared `prepared/user_data/` files preserve the official traded-price Klines. These **three hours on 2024-10-28 UTC have a known source inconsistency**: 19:00 and 21:00 do not match the exchange's individual-trade archive; the 20:00 Kline is flat with zero volume although its aggregate-trade archive contains 39,894 records for the hour. The original hourly CSV also retains these official values.
* `prepared/reconstructed/` contains a **separate research candidate** with those three price bars rebuilt from the exchange's individual market-trade archive and the corresponding daily candle re-aggregated. It is not certified to be the exchange's exact intended Kline: trade IDs have gaps and individual and aggregate records differ in some counts and boundary volume. The common mark-price file is under `prepared/user_data/`. See the audit JSON files in the prepared ZIP for details. The full individual- and aggregate-trade archives are not duplicated here; their public URLs and SHA-256 fingerprints are in the quality report.
* A Freqtrade loader check read the prepared official series: 60,264 hourly price rows, 60,264 hourly mark rows and 2,511 daily price rows. This is a data-loading check, not a backtest or a claim of profitability. Matching previously stored rows does not independently establish that source Klines are correct.
* **Funding is not extended in this package.** The previously published BTC trend funding data end on 2026-10-31. A funding-dependent backtest after that date needs additional validated funding inputs.

## Using the data

Extract the prepared ZIP into a separate workspace. The files under `prepared/user_data/data/binance/futures/` follow Freqtrade's Feather naming convention. Choose the official Klines or the reconstructed research candidate explicitly; the candidate does not contain a separate mark-price file, so use the shared official mark-price file when testing it. Do not mix versions without recording the choice. Existing account databases and live configurations are not included.
