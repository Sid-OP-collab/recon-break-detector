# Reconciliation Break Detector

![CI](https://github.com/Sid-OP-collab/recon-break-detector/actions/workflows/ci.yml/badge.svg)

A trade-ledger reconciliation engine that matches a fund's own broker/PB
blotter against a custodian's copy of the same trades, and automatically
flags and classifies every discrepancy ("break").

**The ledgers are built from a real trade export** — 82 actual trades from
my live portfolio (tracked in
[portfolio-analytics](https://github.com/Sid-OP-collab/portfolio-analytics)),
covering 23 tickers across cash equities and listed call options, not
synthetic placeholder data.

This mirrors the daily workflow described in fund operations / middle-office
job descriptions: *"daily reconciliation of the fund's assets with
custodians, prime brokers, and counterparties"* and *"daily trade matching
services."*

## What it does

1. **`build_real_ledgers.py`** loads a real trade export (`latest_portfolio.csv`),
   cleans it (strips exchange prefixes like `NASDAQ:`, parses timestamps,
   splits equities from listed options), and builds two ledgers —
   `broker_ledger.csv` and `custodian_ledger.csv` — with a set of
   deliberately injected, logged discrepancies (a `breaks_truth.csv`
   ground-truth file is written alongside them so the engine's output can
   be checked for correctness).

   A synthetic-data version (`generate_mock_data.py`) is also included for
   quick, reproducible testing without needing a real trade file.
2. **`reconcile.py`** matches the two ledgers and classifies every break:
   - `MISSING_IN_CUSTODIAN` — trade at broker, not at custodian
   - `MISSING_IN_BROKER` — trade at custodian, not at broker
   - `QUANTITY_MISMATCH` — matched trade, quantity differs
   - `PRICE_MISMATCH` — matched trade, price differs
   - `DATE_MISMATCH` — matched trade, trade date differs
   - `DUPLICATE` — a trade booked more than once on one side

   Matching runs in two passes: first on `trade_id`, then — for anything
   left unresolved — on a composite key, which catches cases where a trade
   genuinely exists on both sides but its reference/ID doesn't line up
   cleanly. This two-pass approach is the same idea as the FIFO lot-matching
   logic in
   [portfolio-analytics](https://github.com/Sid-OP-collab/portfolio-analytics):
   match on the strongest available key, fall back to a looser key rather
   than declaring a false break.

   **The composite key is instrument-aware.** Equities match on
   (ticker, side, quantity). Options additionally require
   (expiry, strike, right) — two call options on the same underlying and
   side can be genuinely different instruments (e.g. a $60-strike vs a
   $65-strike contract), so matching them on ticker alone would silently
   hide a real "wrong strike booked" break as a false clean match.

   Price comparison uses a relative 1bp tolerance rather than a fixed
   dollar threshold, so a $0.001 rounding difference on a $900 stock isn't
   treated the same as one on a $10 stock — with a fallback to an absolute
   threshold for the one real trade in this dataset booked at $0 (a
   promotional fractional share), where a relative tolerance is undefined.

   **Every break carries a materiality score.** A `dollar_impact` figure
   (the $ size of the discrepancy) and a `severity` tier (HIGH/MEDIUM/LOW)
   get computed for each break, and the report sorts by severity first —
   the way a real ops desk triages, since a $0.02 rounding difference
   doesn't need the same attention as a missing $50k trade. DATE_MISMATCH
   is treated differently: since a trade booked on the wrong date still
   nets to the same value, it uses a much higher bar ($50k) before being
   called HIGH, rather than the standard $1k threshold used for economic
   breaks (quantity/price/missing/duplicate). Thresholds are constants at
   the top of `reconcile.py`, deliberately simple and easy to retune — on
   my own (small, fractional-share) real trade history, nothing crosses
   the HIGH bar at all, which is itself the correct behaviour for a
   retail-sized portfolio; a fund with institutional trade sizes would
   want these thresholds set much higher.
3. Output: a CSV and a Markdown report (`output/breaks_report.csv/.md`)
   listing every break — sorted by severity, then $ impact — with a
   human-readable explanation, plus summary counts by severity and type.

## Scope and data notes

- **Dividends are excluded.** The raw export includes dividend/income rows
  (no fill price, since they aren't trades). These are filtered out before
  reconciliation — in practice, income events are typically reconciled
  through a separate cash/income process, not the trade-matching feed.
- **Sensitive fields aren't included.** No account numbers, prices, or PnL
  are anything other than what's needed to demonstrate the matching logic;
  the ledger reflects real trade shape and timing, useful for testing this
  specific engine, not a full statement.

## Limitations / what a production version would need

This is a focused exercise in the matching and classification logic, not a
production reconciliation system. Left out, deliberately, to keep scope
honest:

- **No settlement-date reconciliation** — the raw export has no settle
  date field, so this only reconciles trade dates.
- **No multi-currency or FX handling** — all trades assumed same-currency.
- **No netting** — if the same instrument trades twice in one day on the
  same side, this treats them as two separate rows rather than netting
  quantities, which is how some custodians report.
- **No scale testing** — proven correct on ~80 trades; a real fund's daily
  feed could be orders of magnitude larger, and the current O(n) matching
  with dict lookups should hold up, but hasn't been load-tested.
- **Composite-key collisions remain possible** for two genuinely different
  equity trades that happen to share ticker/side/quantity on the same day
  — a corporate-actions or timestamp-based key would close this gap in a
  production version.

## Running it

The synthetic pipeline (public, safe to run out-of-the-box):

```bash
pip install pytest
python generate_mock_data.py        # builds data/*.csv (random tickers)
python reconcile.py                 # builds output/breaks_report.{csv,md}
pytest tests/ -v                    # 13 tests
```

The real-data pipeline (local only — see note below):

```bash
python build_real_ledgers.py --source data_real/latest_portfolio.csv
python reconcile.py --broker data_real/broker_ledger.csv \
                     --custodian data_real/custodian_ledger.csv \
                     --out data_real/
```

**A note on the real data:** this engine was built and verified against my
own live trade history (82 real trades, 23 tickers, equities + listed
options — [portfolio-analytics](https://github.com/Sid-OP-collab/portfolio-analytics)
is the source). That output isn't in this public repo — real fill prices
and position sizes aren't something to publish — so `data_real/` and
`output_real/` are gitignored. `build_real_ledgers.py` is included so the
real-data logic is fully visible and reviewable; running it just requires
supplying your own trade CSV in the same shape.

## Testing approach

`tests/test_reconcile.py` uses small hand-built fixtures (not the generated
mock data) so each break type — and edge cases like a trade carrying two
simultaneous breaks, or a trade_id that doesn't match but should still be
found — is tested in isolation with a known expected outcome. CI runs the
full suite plus an end-to-end generate → reconcile pass on every push.

## Why this exists

Built as a focused exercise in daily trade-matching / break-detection logic
relevant to fund operations and markets roles — an extension of the
transaction-matching work already done in `portfolio-analytics` (FIFO lot
matching, cash-flow-matched benchmarking), applied to the two-ledger
reconciliation problem instead of the single-ledger cost-basis problem.
