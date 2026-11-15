# Phase 3 independent pre-outcome review

This review was written before the reviewer computed any real forward label or new strategy outcome. Phase 1 registration and Phase 2 results/audits were read. The scope is historical exploratory validation, not an untouched historical holdout or live verification.

## Design decisions needing explicit freezing

- Train January–March 2025, select April–June 2025, and evaluate accounts July 2025–26 April 2026. Keep every coefficient, scaler, symbol reference effect and eligibility decision causal. A single January–June refit is an explicit amendment to the earlier no-refit forward design, not a retroactive claim that the old protocol specified it.
- Select six groups using only the 30-minute primary target, the registered seven-calendar-day block bootstrap, 2,000 draws, seed 20261113, and Holm across all six hypotheses. Unevaluable hypotheses remain in the family with p = 1. Fifteen- and sixty-minute diagnostics cannot select a replacement horizon.
- F1 adds only residual momentum beyond existing own momentum. F6 adds only trade-count relative volume beyond existing quote-volume relative volume. F3 predicts adverse excursion and is eligible only for a risk overlay.
- Build baseline and enhanced models on identical group-specific observation IDs after a common label-validity mask. Record training decision and label ranges. The last training decision must precede the split by 65 minutes; all 60-minute labels must finish strictly before the split.
- At account time, shared opportunity eligibility can depend on selected inputs known at the decision time, but never on any future-label-validity field or later missing-price/funding information. Held-path missing coverage invalidates the experiment; it cannot erase a trade.
- Boundary/recovery inputs only become known after five post-break minutes close. A common delayed-event baseline is necessary to distinguish feature effects from a change in event definition or entry timing. Preserve an unrestricted baseline separately to expose the effect of missing-feature coverage.
- If clock-screened factors are refitted/transferred to event opportunities, label that as an exploratory transfer. Clock prediction evidence does not independently establish event-sample value. Fit the joint event baseline and enhanced model using the same training-event mask.
- Specify empty-selection fallback before outcomes. No passing alpha group means no alpha candidate; F3 alone permits only a risk overlay. No group passing permits a baseline-only negative conclusion.
- Freeze the alpha gate and the exact sign/definition of the F3 prediction difference before results. A gross forecast above 20 bp is a fixed proxy gate, not a guarantee of positive realized net return including funding.
- Preserve original position/risk limits, cooldown, costs, funding accounting, daily loss controls and permanent 8% study stop. Report full-calendar equity, active trading days, cash days and stop date. A result near 8% drawdown does not demonstrate that a continuously operating strategy stays below 15%.
- A 300-day account comparison cannot meet the prior >=365-day capability-CAGR rule. Report cumulative net return and elapsed days; do not headline an extrapolated annual rate as verified capability.

## Independent verification plan

1. Synthetic oracle checks for direction returns, MAE/MFE windows, missing-minute treatment, exit-open treatment and future perturbation; train-only scaler/FE and purge boundaries.
2. Frozen protocol and source identities; each actual model's train/label timestamps; independent group-mask and prediction-loss aggregation reconstruction.
3. Selected-event model and account signal availability; no use of labels or future validity in entry filters.
4. Independent trade ledger: raw/fill P&L, entry/exit fees, slippage, signed funding, net/cash identity, final equity and drawdown. Inspect gap exits and same-minute stop/target priority with synthetic cases.
5. Full common-calendar and common-cost comparisons, preservation checks of original simulator/config/website and prior research.

Serena's LSP was unavailable (language server manager not initialized). The parent explicitly authorized native read/search tools; only files in this audit directory may be written by this reviewer.
