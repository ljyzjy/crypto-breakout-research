# BTCUSDT USD-M hourly data: 2020-01-01 to 2026-11-16 16:00 UTC

This snapshot contains Binance USD-M BTCUSDT perpetual traded-price and mark-price 1-hour candles. Both series use UTC hour-open timestamps and cover **2020-01-01 00:00 through 2026-11-16 16:00 UTC**, inclusive: **60,281 hours each**, with no missing or duplicate hourly timestamps. Capture was made at exchange server time 2026-11-16 17:49:46 UTC; the still-forming 17:00 candle is excluded. This is a snapshot, not a live feed.

## Downloads

| File | Contents | SHA-256 |
| --- | --- | --- |
| [Prepared data](btc-usdm-hourly-2020-20261116T1600Z-prepared.zip) | Freqtrade Feather files for hourly traded price and mark price, daily traded price, and the separate reconstructed candidate | `e3e1277a9f4575554fe4cb5ccf2451c753da932da94823bbadbf03647b2d117f` |
| [Original traded-price fields](BTCUSDT-1h-futures-source-fields-20200101-20261116T1600Z.csv.gz) | 60,281 rows with the 12 official Kline fields, including the anomaly below | `35e8283296e95617b8ab86568f2ffedc47cf8776032792d14e7fb843c24ab0eb` |
| [Original hourly archives](../btc-usdm-hourly-2026-11-15/btc-usdm-hourly-2020-20261115-raw.zip) | 203 official monthly and daily ZIPs through 2026-11-15, with exchange checksum sidecars | `9c31c5c07909e365da0a5f637c9a32a0dc203d5b41bd5a28f09016fcafa944ba` |

The [quality report](quality-report.json) records checks, source gaps and anomaly details. The [archive inventory](../btc-usdm-hourly-2026-11-15/source-inventory-final.json) lists the original ZIP sources. The [price API response](api-price-20261116.json) and [mark API response](api-mark-20261116.json) are saved as received; their last 17:00 candle was incomplete and is excluded from the prepared series. The prepared ZIP has a member-level SHA-256 manifest.

## Data quality and definitions

* **Latest closed hours:** The 203 checksum-verified archive ZIPs cover through 2026-11-15 23:00 UTC. The next 17 completed hours (2026-11-16 00:00–16:00 UTC) came from the official Binance API. Two overlapping hourly records for each series match the archive across all 12 fields. The API snapshot has a recorded local SHA-256, but no exchange-published daily archive checksum was available for this incomplete UTC day.
* **Coverage repair:** Nine days (216 hourly records) missing from official mark-price monthly archives were supplied from corresponding official daily 1h mark-price archives. No interpolation was used. Price and mark timestamps align, but their values are different market quantities. Mark-price volume is a zero placeholder and must not be interpreted as traded volume.
* **Known price anomaly:** Official traded-price Klines on 2024-10-28 19:00, 20:00 and 21:00 UTC disagree with archived individual trades. The 20:00 official Kline is flat with zero volume, although the aggregate-trade archive has 39,894 records in that hour. Official values are preserved in `prepared/user_data/` and the full-field CSV.
* **Separate research candidate:** `prepared/reconstructed/` contains price bars for those three hours estimated from individual trades and the corresponding daily candle re-aggregated. Trade IDs contain gaps and the individual and aggregate feeds differ in some counts and boundary volume; the candidate is not certified to be the exchange's exact intended Kline. The common mark file remains under `prepared/user_data/`. The quality report provides the public trade-source URLs and SHA-256 digests; the full individual- and aggregate-trade archives are not duplicated here.
* **Daily bars and model loading:** The daily Feather files include 2,511 complete UTC days through 2026-11-15; the incomplete 2026-11-16 day is not included. A Freqtrade loader check read 60,281 price hours, 60,281 mark hours and 2,511 daily bars. This checks loading, not trading results. Matching a prior dataset alone does not prove the original source is correct.
* **Funding:** This package does not extend funding. The previously published BTC trend funding data end on 2026-10-31; a funding-dependent backtest after that date needs additional validated funding inputs.

## Using the data

Extract the prepared ZIP into a separate workspace. The files under `prepared/user_data/data/binance/futures/` follow Freqtrade's Feather naming convention. Choose the official Klines or the reconstructed research candidate explicitly; the candidate uses the shared official mark-price file. Record the choice when comparing results. Existing account databases and live configurations are not included.
