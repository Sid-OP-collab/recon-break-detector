"""
generate_mock_data.py

Creates two mock ledgers that simulate the kind of daily feed a fund
operations / middle-office team reconciles:

  - broker_ledger.csv     -> the fund's own broker/PB trade blotter ("truth")
  - custodian_ledger.csv  -> the custodian's copy of the same trades, with a
                             set of deliberately injected discrepancies

A ground-truth file (breaks_truth.csv) is also written, listing exactly
which trade_ids were tampered with and how. This lets the reconciliation
engine's output be checked for correctness (recall/precision), the same
way the portfolio-analytics engine's pytest suite checks TWR/XIRR/lot
matching against known-good numbers.

Run:
    python generate_mock_data.py
"""

import csv
import random
from datetime import datetime, timedelta

random.seed(42)  # reproducible run

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "IONQ", "MU", "SPY"]
SIDES = ["BUY", "SELL"]

N_TRADES = 40
BASE_DATE = datetime(2026, 8, 3)  # a Monday


def gen_base_trades(n=N_TRADES):
    trades = []
    for i in range(1, n + 1):
        trade_id = f"T{i:04d}"
        ticker = random.choice(TICKERS)
        side = random.choice(SIDES)
        quantity = random.choice([10, 25, 50, 75, 100, 150, 200])
        price = round(random.uniform(50, 900), 2)
        trade_date = BASE_DATE + timedelta(days=random.randint(0, 4))
        settle_date = trade_date + timedelta(days=2)  # T+2
        trades.append({
            "trade_id": trade_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "trade_date": trade_date.strftime("%Y-%m-%d"),
            "settle_date": settle_date.strftime("%Y-%m-%d"),
        })
    return trades


def inject_breaks(broker_trades):
    """
    Returns (custodian_trades, truth_log).
    Mutates a *copy* of the broker trades to build the custodian side.
    """
    custodian_trades = [dict(t) for t in broker_trades]
    truth_log = []

    pool = list(range(len(custodian_trades)))
    random.shuffle(pool)

    def take(n):
        chosen = pool[:n]
        del pool[:n]
        return chosen

    # 1. Missing in custodian (3 trades) - drop entirely
    for idx in take(3):
        tid = custodian_trades[idx]["trade_id"]
        truth_log.append({"trade_id": tid, "break_type": "MISSING_IN_CUSTODIAN", "detail": "dropped from custodian feed"})
    dropped_ids = [row["trade_id"] for row in truth_log if row["break_type"] == "MISSING_IN_CUSTODIAN"]
    custodian_trades = [t for t in custodian_trades if t["trade_id"] not in dropped_ids]

    # rebuild pool indices against the now-shrunk list for remaining break types
    remaining_ids = [t["trade_id"] for t in custodian_trades]
    random.shuffle(remaining_ids)

    def take_ids(n):
        chosen = remaining_ids[:n]
        del remaining_ids[:n]
        return chosen

    id_to_idx = {t["trade_id"]: i for i, t in enumerate(custodian_trades)}

    # 2. Quantity mismatch (3 trades)
    for tid in take_ids(3):
        i = id_to_idx[tid]
        old_qty = custodian_trades[i]["quantity"]
        new_qty = old_qty + random.choice([-10, 5, 20])
        custodian_trades[i]["quantity"] = new_qty
        truth_log.append({"trade_id": tid, "break_type": "QUANTITY_MISMATCH",
                           "detail": f"broker qty {old_qty} vs custodian qty {new_qty}"})

    # 3. Price mismatch (2 trades)
    for tid in take_ids(2):
        i = id_to_idx[tid]
        old_price = custodian_trades[i]["price"]
        new_price = round(old_price + random.choice([-1.5, 2.25, 0.75]), 2)
        custodian_trades[i]["price"] = new_price
        truth_log.append({"trade_id": tid, "break_type": "PRICE_MISMATCH",
                           "detail": f"broker price {old_price} vs custodian price {new_price}"})

    # 4. Date mismatch (3 trades) - trade_date shifted by a day at custodian
    for tid in take_ids(3):
        i = id_to_idx[tid]
        old_date = custodian_trades[i]["trade_date"]
        shifted = (datetime.strptime(old_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        custodian_trades[i]["trade_date"] = shifted
        truth_log.append({"trade_id": tid, "break_type": "DATE_MISMATCH",
                           "detail": f"broker trade_date {old_date} vs custodian trade_date {shifted}"})

    # 5. Duplicate booking (1 trade booked twice at custodian)
    for tid in take_ids(1):
        i = id_to_idx[tid]
        dup = dict(custodian_trades[i])
        custodian_trades.append(dup)
        truth_log.append({"trade_id": tid, "break_type": "DUPLICATE",
                           "detail": "trade booked twice in custodian feed"})

    # 6. Missing in broker (2 trades) - custodian has extra trades broker never booked
    for i in range(2):
        fake_id = f"C{100+i:04d}"
        fake = {
            "trade_id": fake_id,
            "ticker": random.choice(TICKERS),
            "side": random.choice(SIDES),
            "quantity": random.choice([10, 25, 50]),
            "price": round(random.uniform(50, 900), 2),
            "trade_date": (BASE_DATE + timedelta(days=random.randint(0, 4))).strftime("%Y-%m-%d"),
            "settle_date": (BASE_DATE + timedelta(days=random.randint(2, 6))).strftime("%Y-%m-%d"),
        }
        custodian_trades.append(fake)
        truth_log.append({"trade_id": fake_id, "break_type": "MISSING_IN_BROKER",
                           "detail": "present at custodian, no matching broker trade"})

    return custodian_trades, truth_log


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    broker_trades = gen_base_trades()
    custodian_trades, truth_log = inject_breaks(broker_trades)

    fieldnames = ["trade_id", "ticker", "side", "quantity", "price", "trade_date", "settle_date"]
    write_csv("data/broker_ledger.csv", broker_trades, fieldnames)
    write_csv("data/custodian_ledger.csv", custodian_trades, fieldnames)
    write_csv("data/breaks_truth.csv", truth_log, ["trade_id", "break_type", "detail"])

    print(f"Broker ledger:    {len(broker_trades)} trades -> data/broker_ledger.csv")
    print(f"Custodian ledger: {len(custodian_trades)} trades -> data/custodian_ledger.csv")
    print(f"Ground-truth breaks logged: {len(truth_log)} -> data/breaks_truth.csv")
