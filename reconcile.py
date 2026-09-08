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

Every break also carries a dollar_impact (the $ size of the discrepancy)
and a severity tier (HIGH/MEDIUM/LOW), so the report can be triaged the
way a real ops desk would: a $0.02 rounding break on 1 share doesn't need
anyone's attention; a missing $50k trade does, immediately.

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

# Materiality thresholds ($ notional). Deliberately simple and centralised
# here so they're easy to tune per-mandate rather than buried in logic.
HIGH_THRESHOLD = 1_000
MEDIUM_THRESHOLD = 100

# DATE_MISMATCH is a timing/operational issue, not an economic one - the
# trade still nets out to the same value, just on the wrong date - so it
# gets its own, much higher bar before being called HIGH. A $10k trade
# booked one day late is routine; a $50k+ one still deserves urgent
# attention because settlement risk scales with size.
DATE_HIGH_THRESHOLD = 50_000


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


def dollar_impact(break_type, b=None, c=None):
    """$ size of the discrepancy. Where a full trade is missing or
    duplicated, that's the full notional value at risk. Where a single
    field differs, it's the $ delta that field represents."""
    if break_type == "QUANTITY_MISMATCH":
        return abs(b["quantity"] - c["quantity"]) * b["price"]
    if break_type == "PRICE_MISMATCH":
        return abs(b["price"] - c["price"]) * b["quantity"]
    if break_type == "DATE_MISMATCH":
        return b["quantity"] * b["price"]
    if break_type in ("MISSING_IN_CUSTODIAN", "DUPLICATE"):
        return b["quantity"] * b["price"]
    if break_type == "MISSING_IN_BROKER":
        return c["quantity"] * c["price"]
    return 0.0


def classify_severity(break_type, impact):
    if break_type == "DATE_MISMATCH":
        return "HIGH" if impact >= DATE_HIGH_THRESHOLD else "LOW"
    if impact >= HIGH_THRESHOLD:
        return "HIGH"
    if impact >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def make_break(trade_id, break_type, detail, b=None, c=None):
    impact = dollar_impact(break_type, b, c)
    return {
        "trade_id": trade_id,
        "break_type": break_type,
        "severity": classify_severity(break_type, impact),
        "dollar_impact": round(impact, 2),
        "detail": detail,
    }


def reconcile(broker_rows, custodian_rows):
    breaks = []       # list of break dicts (trade_id, break_type, severity, dollar_impact, detail)
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
        b, c = b_rows[0], c_rows[0]
        if len(c_rows) > len(b_rows):
            breaks.append(make_break(
                tid, "DUPLICATE",
                f"{len(c_rows)} custodian rows vs {len(b_rows)} broker row(s) for {tid}",
                b=b,
            ))
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
            if field_breaks:
                breaks.extend(field_breaks)
            else:
                breaks.append(make_break(
                    b["trade_id"], "DATE_MISMATCH",
                    f"matched to custodian trade_id {c['trade_id']} via ticker/side/qty only",
                    b=b, c=c,
                ))
        else:
            still_missing_custodian.append(b)

    for b in still_missing_custodian:
        breaks.append(make_break(
            b["trade_id"], "MISSING_IN_CUSTODIAN",
            f"{b['ticker']} {b['side']} {b['quantity']}@{b['price']} on {b['trade_date']} not found at custodian",
            b=b,
        ))

    # Whatever's left in c_by_key (not consumed above) is genuinely missing in broker
    for key, rows in c_by_key.items():
        for c in rows:
            breaks.append(make_break(
                c["trade_id"], "MISSING_IN_BROKER",
                f"{c['ticker']} {c['side']} {c['quantity']}@{c['price']} on {c['trade_date']} not found at broker",
                c=c,
            ))

    return breaks, matched_ok


def compare_fields(tid, b, c, note=None):
    """Given a matched broker/custodian pair, return a list of field-level breaks."""
    out = []
    if abs(b["quantity"] - c["quantity"]) > QUANTITY_TOLERANCE:
        out.append(make_break(
            tid, "QUANTITY_MISMATCH",
            f"broker qty {b['quantity']} vs custodian qty {c['quantity']}" + (f" ({note})" if note else ""),
            b=b, c=c,
        ))
    # Relative (1bp) tolerance normally; falls back to an absolute cent
    # threshold when broker price is exactly 0 (e.g. a free/promo share)
    # since a relative diff is undefined against a zero denominator.
    price_break = (
        abs(b["price"] - c["price"]) > 0.01 if b["price"] == 0
        else abs(b["price"] - c["price"]) / b["price"] > 0.0001
    )
    if price_break:
        out.append(make_break(
            tid, "PRICE_MISMATCH",
            f"broker price {b['price']} vs custodian price {c['price']}" + (f" ({note})" if note else ""),
            b=b, c=c,
        ))
    if b["trade_date"] != c["trade_date"]:
        out.append(make_break(
            tid, "DATE_MISMATCH",
            f"broker trade_date {b['trade_date']} vs custodian trade_date {c['trade_date']}" + (f" ({note})" if note else ""),
            b=b, c=c,
        ))
    return out


def summarize(breaks, matched_ok, broker_rows, custodian_rows):
    by_type = defaultdict(int)
    by_severity = defaultdict(int)
    total_impact = 0.0
    for b in breaks:
        by_type[b["break_type"]] += 1
        by_severity[b["severity"]] += 1
        total_impact += b["dollar_impact"]
    return {
        "broker_trade_count": len(broker_rows),
        "custodian_trade_count": len(custodian_rows),
        "clean_matches": len(matched_ok),
        "total_breaks": len(breaks),
        "total_dollar_impact": round(total_impact, 2),
        "breaks_by_type": dict(sorted(by_type.items())),
        "breaks_by_severity": {s: by_severity.get(s, 0) for s in ("HIGH", "MEDIUM", "LOW")},
    }


SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def sort_key(b):
    return (SEVERITY_ORDER[b["severity"]], -b["dollar_impact"], b["break_type"], b["trade_id"])


def write_report(breaks, summary, out_dir):
    sorted_breaks = sorted(breaks, key=sort_key)

    csv_path = f"{out_dir.rstrip('/')}/breaks_report.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["trade_id", "break_type", "severity", "dollar_impact", "detail"])
        writer.writeheader()
        for b in sorted_breaks:
            writer.writerow(b)

    md_path = f"{out_dir.rstrip('/')}/breaks_report.md"
    with open(md_path, "w") as f:
        f.write("# Reconciliation Break Report\n\n")
        f.write(f"- Broker trades: **{summary['broker_trade_count']}**\n")
        f.write(f"- Custodian trades: **{summary['custodian_trade_count']}**\n")
        f.write(f"- Clean matches: **{summary['clean_matches']}**\n")
        f.write(f"- Total breaks: **{summary['total_breaks']}**\n")
        f.write(f"- Total $ impact: **${summary['total_dollar_impact']:,.2f}**\n\n")

        f.write("## Breaks by severity\n\n")
        f.write("| Severity | Count |\n|---|---|\n")
        for sev in ("HIGH", "MEDIUM", "LOW"):
            f.write(f"| {sev} | {summary['breaks_by_severity'][sev]} |\n")

        f.write("\n## Breaks by type\n\n")
        f.write("| Break type | Count |\n|---|---|\n")
        for btype, count in summary["breaks_by_type"].items():
            f.write(f"| {btype} | {count} |\n")

        f.write("\n## Break detail (sorted by severity, then $ impact)\n\n")
        f.write("| Severity | $ Impact | Trade ID | Break Type | Detail |\n|---|---|---|---|---|\n")
        for b in sorted_breaks:
            f.write(f"| {b['severity']} | ${b['dollar_impact']:,.2f} | {b['trade_id']} | {b['break_type']} | {b['detail']} |\n")

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
    print(f"Total $ impact:   ${summary['total_dollar_impact']:,.2f}")
    print("Breaks by severity:")
    for sev in ("HIGH", "MEDIUM", "LOW"):
        print(f"  {sev}: {summary['breaks_by_severity'][sev]}")
    print("Breaks by type:")
    for btype, count in summary["breaks_by_type"].items():
        print(f"  {btype}: {count}")
    print(f"\nReports written to:\n  {csv_path}\n  {md_path}")


if __name__ == "__main__":
    main()