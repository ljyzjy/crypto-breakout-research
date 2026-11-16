# BTC trend research input package

[Download btc-trend-v4-inputs-2026-10.zip](btc-trend-v4-inputs-2026-10.zip) (1,484,991 bytes). This archive is tracked in the repository and included in a normal clone.

SHA-256: `22dcdd41679546f0f5e37d00aad78e615f05cc8e41e1248e324c0d1402ca65dd`

The package provides prepared BTCUSDT USD-M futures daily prices, funding events, and hourly mark prices for the February–October 2026 study. It includes 42 normalized research source CSVs from February 2025 through October 2026 and 10 unmodified official mark-price ZIP archives. The CSVs are normalized local research copies; they are not byte-identical Binance ZIP files. The archive contains a file-level manifest, checksums, coverage checks, and an audit of four sampled months against official archives.

The data end on 2026-10-31. The package does not automatically replace an existing local data directory or include later funding. The funding file named `1h-funding_rate` contains 8-hour settlement events aligned to nominal hours, not interpolated hourly rates. See the README inside the archive for preparation details.

These inputs do not constitute a completed Freqtrade backtest. The previous attempt could not load exchange metadata because Binance returned HTTP 451; leverage and execution assumptions remain to be validated.
