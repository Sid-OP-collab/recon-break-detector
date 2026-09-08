"""
tests/test_reconcile.py

Unit tests for reconcile.py using small hand-built fixtures (not the
generated mock data), so each break type is tested in isolation with a
known expected outcome - same approach as the pytest suite in
portfolio-analytics for TWR/XIRR/lot-matching.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reconcile import reconcile


def make_trade(trade_id="T0001", ticker="AAPL", side="BUY", quantity=100,
                price=150.0, trade_date="2026-08-03", settle_date="2026-08-05"):
    return {
        "trade_id": trade_id, "ticker": ticker, "side": side,
        "quantity": quantity, "price": price,
        "trade_date": trade_date, "settle_date": settle_date,
    }


def break_types(breaks):
    return sorted(b["break_type"] for b in breaks)


def test_clean_match_produces_no_breaks():
    t = make_trade()
    breaks, matched = reconcile([t], [dict(t)])
    assert breaks == []
    assert matched == ["T0001"]


def test_missing_in_custodian():
    broker = [make_trade("T0001")]
    custodian = []
    breaks, _ = reconcile(broker, custodian)
    assert break_types(breaks) == ["MISSING_IN_CUSTODIAN"]


def test_missing_in_broker():
    broker = []
    custodian = [make_trade("T0001")]
    breaks, _ = reconcile(broker, custodian)
    assert break_types(breaks) == ["MISSING_IN_BROKER"]


def test_quantity_mismatch():
    b = make_trade("T0001", quantity=100)
    c = make_trade("T0001", quantity=90)
    breaks, _ = reconcile([b], [c])
    assert break_types(breaks) == ["QUANTITY_MISMATCH"]


def test_price_mismatch():
    b = make_trade("T0001", price=150.0)
    c = make_trade("T0001", price=148.5)
    breaks, _ = reconcile([b], [c])
    assert break_types(breaks) == ["PRICE_MISMATCH"]


def test_date_mismatch():
    b = make_trade("T0001", trade_date="2026-08-03")
    c = make_trade("T0001", trade_date="2026-08-04")
    breaks, _ = reconcile([b], [c])
    assert break_types(breaks) == ["DATE_MISMATCH"]


def test_duplicate_booking():
    b = [make_trade("T0001")]
    c = [make_trade("T0001"), make_trade("T0001")]
    breaks, _ = reconcile(b, c)
    assert "DUPLICATE" in break_types(breaks)


def test_multiple_field_breaks_on_one_trade():
    """A trade can be both a quantity AND a price break at once - both
    should be reported, not just the first one found."""
    b = make_trade("T0001", quantity=100, price=150.0)
    c = make_trade("T0001", quantity=90, price=148.5)
    breaks, _ = reconcile([b], [c])
    assert break_types(breaks) == ["PRICE_MISMATCH", "QUANTITY_MISMATCH"]


def test_composite_key_rescues_shifted_trade_id():
    """If trade_id itself is corrupted/mismatched but ticker+side+quantity
    line up, the engine should still find the trade and classify it based
    on whatever field actually differs (here: trade_date)."""
    b = make_trade("T0001", trade_date="2026-08-03")
    c = make_trade("T9999", trade_date="2026-08-04")  # different id, same key
    breaks, _ = reconcile([b], [c])
    assert len(breaks) == 1
    assert breaks[0]["break_type"] == "DATE_MISMATCH"


def test_no_trade_silently_dropped():
    """Every trade on either side must end up either matched or in the
    breaks list - nothing should vanish."""
    broker = [make_trade("T0001"), make_trade("T0002", ticker="MSFT")]
    custodian = [make_trade("T0001")]
    breaks, matched = reconcile(broker, custodian)
    accounted_for = set(matched) | {b["trade_id"] for b in breaks}
    assert "T0001" in accounted_for
    assert "T0002" in accounted_for
