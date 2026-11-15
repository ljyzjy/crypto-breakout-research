# Public market data snapshot

The [market data release](https://github.com/ljyzjy/crypto-breakout-research/releases/tag/market-data-2026-11-15) is intended to hold 1,953 public Binance archives, totaling 8,030,500,775 bytes before tar packaging. The source files cover selected inputs used by the model and breakout research: 314 USD-M futures trade archives, 136 aggregate-trade archives, 699 futures kline archives, 339 futures mark-price kline archives, 321 funding-rate archives, and 144 spot kline archives.

This is a collection of selected project inputs, not a continuous record of every market, date, or research experiment. Local copies provided the fingerprints of 1,531 archives. For a further 422 archives, the research checkpoints retained a verified source fingerprint and file size; the publication workflow obtains those archives again from Binance. The complete list, source URLs, byte counts, individual SHA-256 hashes, and release-part assignments are in [`source-manifest.json`](source-manifest.json). Binance's public data portal is the upstream source: <https://data.binance.vision/>.

Download all seven `market-data-part-XX.tar` assets from the release and extract each into the same directory. On Windows PowerShell, after saving the parts in the current directory:

```powershell
New-Item -ItemType Directory -Force -Path data/raw | Out-Null
Get-ChildItem market-data-part-*.tar | ForEach-Object { tar -xf $_.FullName -C data/raw }
```

The extracted files are the original ZIP archives, organized beneath `data/raw/binance/` according to their upstream URL paths. They are hosted as release assets rather than included in a normal `git clone`. Historical scripts can require additional processing and path changes; the presence of these data files does not by itself reproduce every backtest.

The workflow downloads each archive from its recorded source and verifies its size and SHA-256 digest before packaging it. A complete release is published only after all seven parts have been successfully uploaded.
