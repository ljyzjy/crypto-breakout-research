"""Export auditable CSV/Markdown from Freqtrade's actual result ZIPs."""
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "user_data" / "backtest_results"


def main():
    selected = {}
    for path in sorted(RESULTS.glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            payload = json.loads(archive.read(path.stem + ".json"))
            if "SpotTrendV1" not in payload.get("strategy", {}):
                continue
            stats = payload["strategy"]["SpotTrendV1"]
            if not stats.get("trades"):
                continue
            fee = stats["trades"][0]["fee_open"]
            detail = stats.get("timeframe_detail") or "1h"
            key = (stats["backtest_start"][:4], fee, detail)
            wallet_file = next(n for n in archive.namelist() if n.endswith("_wallet.feather"))
            wallet = pd.read_feather(io.BytesIO(archive.read(wallet_file)))
            equity = wallet.groupby("date")["total_quote"].sum().sort_index()
            equity.loc[pd.Timestamp(stats["backtest_start"], tz="UTC")] = stats["starting_balance"]
            equity = equity.sort_index()
            drawdown = (1 - equity / equity.cummax()).max()
            selected[key] = (stats, fee, detail, float(drawdown), path.name, equity)
    rows = []
    report = ["# 实际回测结果", "", "生成自本机 Freqtrade 2026.10 的结果文件。初始虚拟资金 1,000 USDT，每笔 100 USDT，最多两笔。",
              "所有日期均为 UTC。最大回撤用钱包逐时市值（包括未实现盈亏）重算，可能与仅基于已平仓交易的默认摘要不同。",
              "", "| 区间 | 成交细度 | 每边费用 | 交易数 | 净收益 USDT | 账户收益 | 权益最大回撤 | Profit Factor |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for key, (s, fee, detail, dd, name, equity) in sorted(selected.items()):
        row = {"start_utc": s["backtest_start"], "end_utc": s["backtest_end"],
               "timeframe_detail": detail, "fee_per_side": fee, "trades": s["total_trades"],
               "profit_usdt": s["profit_total_abs"], "return_pct": s["profit_total"] * 100,
               "equity_max_drawdown_pct": dd * 100, "profit_factor": s["profit_factor"],
               "winrate_pct": s["winrate"] * 100, "source_zip": name}
        rows.append(row)
        report.append(f"| {s['backtest_start'][:10]}—{s['backtest_end'][:10]} | {detail} | {fee:.2%} | {s['total_trades']} | {s['profit_total_abs']:.2f} | {s['profit_total']:.2%} | {dd:.2%} | {s['profit_factor']:.3f} |")
        equity.rename("equity_usdt").to_csv(ROOT / f"equity-{key[0]}-{fee}-{detail}.csv")
    report += ["", "## 评估期基准与单币贡献", ""]
    baseline = selected.get(("2025", 0.001, "1h"))
    if baseline:
        stats, fee, *_ = baseline
        start = pd.Timestamp(stats["backtest_start"], tz="UTC")
        end = pd.Timestamp(stats["backtest_end"], tz="UTC")
        holdings = []
        for pair in ["BTC", "ETH"]:
            data = pd.read_feather(ROOT / "user_data" / "data" / "binance" / f"{pair}_USDT-1h.feather")
            data = data[(data.date >= start) & (data.date <= end)].set_index("date")
            quantity = 100 / (data.open.iloc[0] * (1 + fee))
            holdings.append(quantity * data.close)
        value = 800 + holdings[0] + holdings[1]
        liquidation_final = 800 + (holdings[0].iloc[-1] + holdings[1].iloc[-1]) * (1 - fee)
        hold_dd = float((1 - value / value.cummax()).max())
        report += [f"- 全现金：0%（不计利息）。",
                   f"- 买入持有：期初各用 100 USDT（含买入费）买 BTC/ETH，保留 800 USDT 现金；期末假设卖出并扣费，账户收益 {(liquidation_final / 1000 - 1):.2%}。逐时持仓市值最大回撤 {hold_dd:.2%}（不预扣退出费）。",
                   "- 基准与趋势策略的持仓持续时间不同；这里只对齐初始资金配置，不能据此声称风险暴露完全相同。"]
        for pair in stats["results_per_pair"]:
            if pair["key"] != "TOTAL":
                report.append(f"- {pair['key']} 策略贡献：{pair['profit_total_abs']:.2f} USDT，{pair['trades']} 笔。")
        months = stats["periodic_breakdown"]["month"]
        worst = min(months, key=lambda m: m["profit_abs"])
        best = max(months, key=lambda m: m["profit_abs"])
        report += [f"- 已平仓利润最差月：{worst['date']}，{worst['profit_abs']:.2f} USDT；最好月：{best['date']}，{best['profit_abs']:.2f} USDT。",
                   "", "## 当前结论", "",
                   "基线没有通过真钱启用门槛：开发/验证区间亏损，评估期双倍费用下转负，而且基础费用下利润主要来自 ETH。当前适合技术练习和模拟验收，不建议直接实盘。",
                   "策略参数没有根据这些结果重新优化。未来若修改规则，需另立版本和评估计划。", "",
                   "5 分钟细化仍不等于逐笔撮合；费用压力情景不是精确滑点模型。上述结果是历史仿真，非真实账户收益。"]
    report += ["", "## 结果追溯", ""]
    report += [f"- `{r['source_zip']}`：{r['start_utc']}—{r['end_utc']}，fee={r['fee_per_side']}，detail={r['timeframe_detail']}。" for r in rows]
    pd.DataFrame(rows).to_csv(ROOT / "backtest_summary.csv", index=False, encoding="utf-8-sig")
    (ROOT / "BACKTEST_RESULTS.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(pd.DataFrame(rows).drop(columns=["source_zip"]).to_string(index=False))


if __name__ == "__main__":
    main()
