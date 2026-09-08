# Reconciliation Break Report

- Broker trades: **40**
- Custodian trades: **40**
- Clean matches: **29**
- Total breaks: **14**

## Breaks by type

| Break type | Count |
|---|---|
| DATE_MISMATCH | 3 |
| DUPLICATE | 1 |
| MISSING_IN_BROKER | 2 |
| MISSING_IN_CUSTODIAN | 3 |
| PRICE_MISMATCH | 2 |
| QUANTITY_MISMATCH | 3 |

## Break detail

| Trade ID | Break Type | Detail |
|---|---|---|
| T0010 | DATE_MISMATCH | broker trade_date 2026-08-03 vs custodian trade_date 2026-08-04 |
| T0011 | DATE_MISMATCH | broker trade_date 2026-08-03 vs custodian trade_date 2026-08-04 |
| T0013 | DATE_MISMATCH | broker trade_date 2026-08-05 vs custodian trade_date 2026-08-06 |
| T0036 | DUPLICATE | 2 custodian rows vs 1 broker row(s) for T0036 |
| C0100 | MISSING_IN_BROKER | SPY BUY 50.0@316.56 on 2026-08-03 not found at broker |
| C0101 | MISSING_IN_BROKER | IONQ BUY 10.0@866.66 on 2026-08-03 not found at broker |
| T0023 | MISSING_IN_CUSTODIAN | MU SELL 10.0@692.41 on 2026-08-03 not found at custodian |
| T0026 | MISSING_IN_CUSTODIAN | MU SELL 100.0@781.66 on 2026-08-03 not found at custodian |
| T0029 | MISSING_IN_CUSTODIAN | MU BUY 100.0@825.73 on 2026-08-05 not found at custodian |
| T0017 | PRICE_MISMATCH | broker price 318.14 vs custodian price 316.64 |
| T0040 | PRICE_MISMATCH | broker price 651.66 vs custodian price 650.16 |
| T0005 | QUANTITY_MISMATCH | broker qty 75.0 vs custodian qty 65.0 |
| T0016 | QUANTITY_MISMATCH | broker qty 200.0 vs custodian qty 190.0 |
| T0024 | QUANTITY_MISMATCH | broker qty 200.0 vs custodian qty 205.0 |
