# Reconciliation Break Detector

A trade-ledger reconciliation engine that matches a fund's own broker/PB
blotter against a custodian's copy of the same trades, and automatically
flags and classifies every discrepancy ("break").

This mirrors the daily workflow described in fund operations / middle-office
job descriptions: *"daily reconciliation of the fund's assets with
custodians, prime brokers, and counterparties"* and *"daily trade matching
services."*

## What it does

1. **`generate_mock_data.py`** builds two CSV ledgers — `broker_ledger.csv`
   and `custodian_ledger.csv` — representing the same underlying trades,
   with a set of deliberately injected, logged discrepancies (a
   `breaks_truth.csv` ground-truth file is written alongside them so the
   engine's output can be checked for correctness).
2. **`reconcile.py`** matches the two ledgers and classifies every break:
   - `MISSING_IN_CUSTODIAN` — trade at broker, not at custodian
   - `MISSING_IN_BROKER` — trade at custodian, not at broker
   - `QUANTITY_MISMATCH` — matched trade, quantity differs
   - `PRICE_MISMATCH` — matched trade, price differs
   - `DATE_MISMATCH` — matched trade, trade date differs
   - `DUPLICATE` — a trade booked more than once on one side

   Matching runs in two passes: first on `trade_id`, then — for anything
   left unresolved — on a composite key (ticker, side, quantity), which
   catches cases where a trade genuinely exists on both sides but its
   reference/ID doesn't line up cleanly. This two-pass approach is the same
   idea as the FIFO lot-matching logic in
   [portfolio-analytics](https://github.com/Sid-OP-collab/portfolio-analytics):
   match on the strongest available key, fall back to a looser key rather
   than declaring a false break.
3. Output: a CSV and a Markdown report (`output/breaks_report.csv/.md`)
   listing every break with a human-readable explanation, plus a summary
   count by break type.

## Running it

```bash
pip install pytest
python generate_mock_data.py        # builds data/*.csv
python reconcile.py                 # builds output/breaks_report.{csv,md}
pytest tests/ -v                    # 10 tests, one+ per break type
```

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
