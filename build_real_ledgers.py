"""
build_real_ledgers.py

Builds broker_ledger.csv and custodian_ledger.csv from a REAL trade export
(latest_portfolio.csv) instead of synthetic random data, then injects the
same deliberate discrepancies as generate_mock_data.py did.

Key difference from the synthetic version: the real export mixes cash
equities with listed call options. Two option trades can share the same
underlying ticker and side but be genuinely different instruments (a $60
strike ASTS call is not the same position as a $19 strike SOFI call), so
matching on ticker+side+quantity alone is wrong for options - it needs to
also match on expiry+strike+right. Equities don't have those fields, so
they naturally fall back to the simpler equity-only key.

Run:
    python build_real_ledgers.py --source latest_portfolio.csv
"""

import argparse
import csv
import random
from datetime import datetime, timedelta

random.seed(42)

FIELDS = ["trade_id", "ticker", "instrument_type", "side", "quantity", "price",
          "trade_date", "expiry", "strike", "right"]


def clean_ticker(raw_symbol):
    """Strip exchange prefix, e.g. 'NASDAQ:AVGO' -> 'AVGO'."""
    return raw_symbol.split(":")[-1].strip()


def parse_closing_time(raw):
    """'03-09-2026 23:20' -> '2026-09-03' (DD-MM-YYYY -> YYYY-MM-DD)."""
    dt = datetime.strptime(raw.strip(), "%d-%m-%Y %H:%M")
    return dt.strftime("%Y-%m-%d")


def load_real_trades(path):
    """Loads BUY/SELL trades only. Dividend rows are cash/income events, not
    trades - they carry no fill price and are reconciled through a separate
    income process in practice, so they're excluded here rather than forced
    into a trade-matching schema they don't fit."""
    trades = []
    skipped_dividends = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Side"].strip().upper() == "DIVIDEND":
                skipped_dividends += 1
                continue
            is_option = bool(row.get("Right", "").strip())
            trades.append({
                "trade_id": f"T{len(trades) + 1:04d}",
                "ticker": clean_ticker(row["Symbol"]),
                "instrument_type": "OPTION" if is_option else "EQUITY",
                "side": row["Side"].strip().upper(),
                "quantity": round(float(row["Qty"]), 6),
                "price": round(float(row["Fill Price"]), 4),
                "trade_date": parse_closing_time(row["Closing Time"]),
                "expiry": row.get("Expiry", "").strip(),
                "strike": row.get("Strike", "").strip(),
                "right": row.get("Right", "").strip(),
            })
    print(f"(skipped {skipped_dividends} dividend/income rows - not trades)")
    return trades


def inject_breaks(broker_trades):
    custodian_trades = [dict(t) for t in broker_trades]
    truth_log = []

    all_ids = [t["trade_id"] for t in custodian_trades]
    random.shuffle(all_ids)
    pool = iter(all_ids)

    def take(n):
        return [next(pool) for _ in range(n)]

    id_to_idx = {t["trade_id"]: i for i, t in enumerate(custodian_trades)}

    # 1. Missing in custodian (3 trades)
    drop_ids = take(3)
    for tid in drop_ids:
        truth_log.append({"trade_id": tid, "break_type": "MISSING_IN_CUSTODIAN", "detail": "dropped from custodian feed"})
    custodian_trades = [t for t in custodian_trades if t["trade_id"] not in drop_ids]
    id_to_idx = {t["trade_id"]: i for i, t in enumerate(custodian_trades)}

    # 2. Quantity mismatch (3 trades) - skip options, quantity=1 contract is too coarse to nudge
    eq_candidates = [t["trade_id"] for t in custodian_trades if t["instrument_type"] == "EQUITY"]
    random.shuffle(eq_candidates)
    for tid in eq_candidates[:3]:
        i = id_to_idx[tid]
        old_qty = custodian_trades[i]["quantity"]
        new_qty = round(old_qty * random.choice([0.9, 1.05, 1.15]), 6)
        custodian_trades[i]["quantity"] = new_qty
        truth_log.append({"trade_id": tid, "break_type": "QUANTITY_MISMATCH",
                           "detail": f"broker qty {old_qty} vs custodian qty {new_qty}"})
    used = set(eq_candidates[:3])

    # 3. Price mismatch (3 trades)
    remaining_ids = [t["trade_id"] for t in custodian_trades if t["trade_id"] not in used]
    random.shuffle(remaining_ids)
    for tid in remaining_ids[:3]:
        i = id_to_idx[tid]
        old_price = custodian_trades[i]["price"]
        new_price = round(old_price * random.choice([0.98, 1.02, 1.005]), 4)
        custodian_trades[i]["price"] = new_price
        truth_log.append({"trade_id": tid, "break_type": "PRICE_MISMATCH",
                           "detail": f"broker price {old_price} vs custodian price {new_price}"})
    used.update(remaining_ids[:3])

    # 4. Date mismatch (3 trades)
    remaining_ids = [t["trade_id"] for t in custodian_trades if t["trade_id"] not in used]
    random.shuffle(remaining_ids)
    for tid in remaining_ids[:3]:
        i = id_to_idx[tid]
        old_date = custodian_trades[i]["trade_date"]
        shifted = (datetime.strptime(old_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        custodian_trades[i]["trade_date"] = shifted
        truth_log.append({"trade_id": tid, "break_type": "DATE_MISMATCH",
                           "detail": f"broker trade_date {old_date} vs custodian trade_date {shifted}"})
    used.update(remaining_ids[:3])

    # 5. Duplicate booking (1 trade)
    remaining_ids = [t["trade_id"] for t in custodian_trades if t["trade_id"] not in used]
    random.shuffle(remaining_ids)
    dup_tid = remaining_ids[0]
    dup_row = dict(custodian_trades[id_to_idx[dup_tid]])
    custodian_trades.append(dup_row)
    truth_log.append({"trade_id": dup_tid, "break_type": "DUPLICATE", "detail": "trade booked twice in custodian feed"})

    # 6. Missing in broker (2 phantom trades, one equity one option-shaped)
    phantom_1 = {
        "trade_id": "C0100", "ticker": "AAPL", "instrument_type": "EQUITY",
        "side": "BUY", "quantity": 0.5, "price": 225.10,
        "trade_date": "2026-08-15", "expiry": "", "strike": "", "right": "",
    }
    phantom_2 = {
        "trade_id": "C0101", "ticker": "TSLA", "instrument_type": "OPTION",
        "side": "BUY", "quantity": 1, "price": 42.0,
        "trade_date": "2026-08-20", "expiry": "20-11-2026", "strike": "250", "right": "C",
    }
    for p in (phantom_1, phantom_2):
        custodian_trades.append(p)
        truth_log.append({"trade_id": p["trade_id"], "break_type": "MISSING_IN_BROKER",
                           "detail": f"{p['ticker']} {p['side']} {p['quantity']} not found at broker"})

    return custodian_trades, truth_log


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data_real/latest_portfolio.csv")
    parser.add_argument("--out-dir", default="data_real")
    args = parser.parse_args()

    broker_trades = load_real_trades(args.source)
    custodian_trades, truth_log = inject_breaks(broker_trades)

    write_csv(f"{args.out_dir}/broker_ledger.csv", broker_trades, FIELDS)
    write_csv(f"{args.out_dir}/custodian_ledger.csv", custodian_trades, FIELDS)
    write_csv(f"{args.out_dir}/breaks_truth.csv", truth_log, ["trade_id", "break_type", "detail"])

    n_eq = sum(1 for t in broker_trades if t["instrument_type"] == "EQUITY")
    n_opt = sum(1 for t in broker_trades if t["instrument_type"] == "OPTION")
    print(f"Broker ledger:    {len(broker_trades)} trades ({n_eq} equity, {n_opt} option) -> {args.out_dir}/broker_ledger.csv")
    print(f"Custodian ledger: {len(custodian_trades)} trades -> {args.out_dir}/custodian_ledger.csv")
    print(f"Ground-truth breaks logged: {len(truth_log)} -> {args.out_dir}/breaks_truth.csv")
    print(f"\nRun: python reconcile.py --broker {args.out_dir}/broker_ledger.csv --custodian {args.out_dir}/custodian_ledger.csv --out {args.out_dir}/")
