# Reconciliation Break Report

- Broker trades: **40**
- Custodian trades: **40**
- Clean matches: **29**
- Total breaks: **14**
- Total $ impact: **$321,088.75**

## Breaks by severity

| Severity | Count |
|---|---|
| HIGH | 10 |
| MEDIUM | 1 |
| LOW | 3 |

## Breaks by type

| Break type | Count |
|---|---|
| DATE_MISMATCH | 3 |
| DUPLICATE | 1 |
| MISSING_IN_BROKER | 2 |
| MISSING_IN_CUSTODIAN | 3 |
| PRICE_MISMATCH | 2 |
| QUANTITY_MISMATCH | 3 |

## Break detail (sorted by severity, then $ impact)

| Severity | $ Impact | Trade ID | Break Type | Detail |
|---|---|---|---|---|
| HIGH | $82,573.00 | T0029 | MISSING_IN_CUSTODIAN | MU BUY 100.0@825.73 on 2026-08-05 not found at custodian |
| HIGH | $78,166.00 | T0026 | MISSING_IN_CUSTODIAN | MU SELL 100.0@781.66 on 2026-08-03 not found at custodian |
| HIGH | $59,196.00 | T0011 | DATE_MISMATCH | broker trade_date 2026-08-03 vs custodian trade_date 2026-08-04 |
| HIGH | $20,989.50 | T0036 | DUPLICATE | 2 custodian rows vs 1 broker row(s) for T0036 |
| HIGH | $15,828.00 | C0100 | MISSING_IN_BROKER | SPY BUY 50.0@316.56 on 2026-08-03 not found at broker |
| HIGH | $8,666.60 | C0101 | MISSING_IN_BROKER | IONQ BUY 10.0@866.66 on 2026-08-03 not found at broker |
| HIGH | $7,030.70 | T0016 | QUANTITY_MISMATCH | broker qty 200.0 vs custodian qty 190.0 |
| HIGH | $6,924.10 | T0023 | MISSING_IN_CUSTODIAN | MU SELL 10.0@692.41 on 2026-08-03 not found at custodian |
| HIGH | $5,508.80 | T0005 | QUANTITY_MISMATCH | broker qty 75.0 vs custodian qty 65.0 |
| HIGH | $3,142.05 | T0024 | QUANTITY_MISMATCH | broker qty 200.0 vs custodian qty 205.0 |
| MEDIUM | $300.00 | T0017 | PRICE_MISMATCH | broker price 318.14 vs custodian price 316.64 |
| LOW | $21,345.00 | T0010 | DATE_MISMATCH | broker trade_date 2026-08-03 vs custodian trade_date 2026-08-04 |
| LOW | $11,404.00 | T0013 | DATE_MISMATCH | broker trade_date 2026-08-05 vs custodian trade_date 2026-08-06 |
| LOW | $15.00 | T0040 | PRICE_MISMATCH | broker price 651.66 vs custodian price 650.16 |
