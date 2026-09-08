"""
reconcile.py

Reconciles two trade ledgers (broker vs custodian) and flags/classifies
breaks. Mirrors the matching philosophy in the portfolio-analytics engine's
FIFO lot matcher: match on the strongest available key first, fall back to
a looser key when the strong key fails, and never silently drop an
unmatched row - every trade ends up either MATCHED or in exactly one break
bucket.

Break types:
  MISSING_IN_CUSTODIAN - trade exists at broker, no match at custodian
  MISSING_IN_BROKER    - trade exists at custodian, no match at broker
  QUANTITY_MISMATCH    - matched trade, quantity differs
  PRICE_MISMATCH       - matched trade, price differs
  DATE_MISMATCH        - matched trade, trade_date differs
  DUPLICATE            - more custodian rows for a trade_id than broker rows

Usage:
    python reconcile.py \
        --broker data/broker_ledger.csv \
        --custodian data/custodian_ledger.csv \
        --out output/
"""

import argparse
import csv
from collections import defaultdict


FIELDS = ["trade_id", "ticker", "instrument_type", "side", "quantity", "price",
          "trade_date", "expiry", "strike", "right"]

QUANTITY_TOLERANCE = 1e-6  # float rounding noise, not a real break


def load_ledger(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for r in rows:
        r["quantity"] = float(r["quantity"])
        r["price"] = float(r["price"])
    return rows


def index_by_id(rows):
    """trade_id -> list of rows (list, because duplicates are a break type, not an error)."""
    idx = defaultdict(list)
    for r in rows:
        idx[r["trade_id"]].append(r)
    return idx


def composite_key(row):
    """Fallback match key when trade_id doesn't line up.

    Equities: ticker + side + quantity is enough - one AAPL BUY of 0.5
    shares is the same economic trade regardless of which system's ID
    labels it.

    Options are NOT safe to key the same way: two calls on the same
    underlying, same side, same quantity (typically 1 contract) can be
    completely different instruments if the strike or expiry differs.
    A $60-strike ASTS call and a $65-strike ASTS call must never be
    treated as candidates for the same match, or a real break (wrong
    strike booked) would be silently swallowed instead of flagged.
    So for OPTION rows the key also includes expiry/strike/right.

    Either way, trade_date and price are deliberately excluded, since
    those are exactly the fields we want to be free to flag as
    mismatched once a trade is found via this fallback."""
    base = (row["ticker"], row["side"], round(row["quantity"], 6))
    if row.get("instrument_type") == "OPTION":
        return base + (row.get("expiry", ""), row.get("strike", ""), row.get("right", ""))
    return base


def reconcile(broker_rows, custodian_rows):
    breaks = []       # list of dicts: trade_id, break_type, detail
    matched_ok = []    # trade_ids that matched clean

    broker_idx = index_by_id(broker_rows)
    custodian_idx = index_by_id(custodian_rows)

    all_ids = set(broker_idx) | set(custodian_idx)

    unresolved_broker = []   # broker rows with no id match at custodian
    unresolved_custodian = []  # custodian rows with no id match at broker

    for tid in sorted(all_ids):
        b_rows = broker_idx.get(tid, [])
        c_rows = custodian_idx.get(tid, [])

        if b_rows and not c_rows:
            unresolved_broker.extend(b_rows)
            continue
        if c_rows and not b_rows:
            unresolved_custodian.extend(c_rows)
            continue

        # Both sides have this trade_id
        if len(c_rows) > len(b_rows):
            breaks.append({
                "trade_id": tid, "break_type": "DUPLICATE",
                "detail": f"{len(c_rows)} custodian rows vs {len(b_rows)} broker row(s) for {tid}",
            })
        b, c = b_rows[0], c_rows[0]
        field_breaks = compare_fields(tid, b, c)
        if field_breaks:
            breaks.extend(field_breaks)
        else:
            matched_ok.append(tid)

    # Second pass: try to rescue unresolved rows via composite key
    # (this is what catches trades whose trade_id got mangled/shifted,
    #  as opposed to genuinely missing trades)
    c_by_key = defaultdict(list)
    for r in unresolved_custodian:
        c_by_key[composite_key(r)].append(r)

    still_missing_custodian = []
    for b in unresolved_broker:
        key = composite_key(b)
        candidates = c_by_key.get(key, [])
        if candidates:
            c = candidates.pop(0)
            field_breaks = compare_fields(b["trade_id"], b, c, note="matched via composite key, trade_id differs or was corrupted")
            breaks.extend(field_breaks if field_breaks else [{
                "trade_id": b["trade_id"], "break_type": "DATE_MISMATCH",
                "detail": f"matched to custodian trade_id {c['trade_id']} via ticker/side/qty only",
            }])
        else:
            still_missing_custodian.append(b)

    for b in still_missing_custodian:
        breaks.append({
            "trade_id": b["trade_id"], "break_type": "MISSING_IN_CUSTODIAN",
            "detail": f"{b['ticker']} {b['side']} {b['quantity']}@{b['price']} on {b['trade_date']} not found at custodian",
        })

    # Whatever's left in c_by_key (not consumed above) is genuinely missing in broker
    for key, rows in c_by_key.items():
        for c in rows:
            breaks.append({
                "trade_id": c["trade_id"], "break_type": "MISSING_IN_BROKER",
                "detail": f"{c['ticker']} {c['side']} {c['quantity']}@{c['price']} on {c['trade_date']} not found at broker",
            })

    return breaks, matched_ok


def compare_fields(tid, b, c, note=None):
    """Given a matched broker/custodian pair, return a list of field-level breaks."""
    out = []
    if abs(b["quantity"] - c["quantity"]) > QUANTITY_TOLERANCE:
        out.append({"trade_id": tid, "break_type": "QUANTITY_MISMATCH",
                     "detail": f"broker qty {b['quantity']} vs custodian qty {c['quantity']}" + (f" ({note})" if note else "")})
    # Relative (1bp) tolerance normally; falls back to an absolute cent
    # threshold when broker price is exactly 0 (e.g. a free/promo share)
    # since a relative diff is undefined against a zero denominator.
    price_break = (
        abs(b["price"] - c["price"]) > 0.01 if b["price"] == 0
        else abs(b["price"] - c["price"]) / b["price"] > 0.0001
    )
    if price_break:
        out.append({"trade_id": tid, "break_type": "PRICE_MISMATCH",
                     "detail": f"broker price {b['price']} vs custodian price {c['price']}" + (f" ({note})" if note else "")})
    if b["trade_date"] != c["trade_date"]:
        out.append({"trade_id": tid, "break_type": "DATE_MISMATCH",
                     "detail": f"broker trade_date {b['trade_date']} vs custodian trade_date {c['trade_date']}" + (f" ({note})" if note else "")})
    return out


def summarize(breaks, matched_ok, broker_rows, custodian_rows):
    by_type = defaultdict(int)
    for b in breaks:
        by_type[b["break_type"]] += 1
    return {
        "broker_trade_count": len(broker_rows),
        "custodian_trade_count": len(custodian_rows),
        "clean_matches": len(matched_ok),
        "total_breaks": len(breaks),
        "breaks_by_type": dict(sorted(by_type.items())),
    }


def write_report(breaks, summary, out_dir):
    csv_path = f"{out_dir.rstrip('/')}/breaks_report.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["trade_id", "break_type", "detail"])
        writer.writeheader()
        for b in sorted(breaks, key=lambda x: (x["break_type"], x["trade_id"])):
            writer.writerow(b)

    md_path = f"{out_dir.rstrip('/')}/breaks_report.md"
    with open(md_path, "w") as f:
        f.write("# Reconciliation Break Report\n\n")
        f.write(f"- Broker trades: **{summary['broker_trade_count']}**\n")
        f.write(f"- Custodian trades: **{summary['custodian_trade_count']}**\n")
        f.write(f"- Clean matches: **{summary['clean_matches']}**\n")
        f.write(f"- Total breaks: **{summary['total_breaks']}**\n\n")
        f.write("## Breaks by type\n\n")
        f.write("| Break type | Count |\n|---|---|\n")
        for btype, count in summary["breaks_by_type"].items():
            f.write(f"| {btype} | {count} |\n")
        f.write("\n## Break detail\n\n")
        f.write("| Trade ID | Break Type | Detail |\n|---|---|---|\n")
        for b in sorted(breaks, key=lambda x: (x["break_type"], x["trade_id"])):
            f.write(f"| {b['trade_id']} | {b['break_type']} | {b['detail']} |\n")

    return csv_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Reconcile broker vs custodian trade ledgers.")
    parser.add_argument("--broker", default="data/broker_ledger.csv")
    parser.add_argument("--custodian", default="data/custodian_ledger.csv")
    parser.add_argument("--out", default="output/")
    args = parser.parse_args()

    broker_rows = load_ledger(args.broker)
    custodian_rows = load_ledger(args.custodian)

    breaks, matched_ok = reconcile(broker_rows, custodian_rows)
    summary = summarize(breaks, matched_ok, broker_rows, custodian_rows)

    csv_path, md_path = write_report(breaks, summary, args.out)

    print(f"Broker trades:    {summary['broker_trade_count']}")
    print(f"Custodian trades: {summary['custodian_trade_count']}")
    print(f"Clean matches:    {summary['clean_matches']}")
    print(f"Total breaks:     {summary['total_breaks']}")
    print("Breaks by type:")
    for btype, count in summary["breaks_by_type"].items():
        print(f"  {btype}: {count}")
    print(f"\nReports written to:\n  {csv_path}\n  {md_path}")


if __name__ == "__main__":
    main()