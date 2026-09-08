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


def make_trade(trade_id="T0001", ticker="AAPL", instrument_type="EQUITY", side="BUY",
                quantity=100, price=150.0, trade_date="2026-08-03",
                expiry="", strike="", right=""):
    return {
        "trade_id": trade_id, "ticker": ticker, "instrument_type": instrument_type,
        "side": side, "quantity": quantity, "price": price, "trade_date": trade_date,
        "expiry": expiry, "strike": strike, "right": right,
    }


def make_option(trade_id="T0001", ticker="ASTS", side="BUY", quantity=1,
                 price=550.0, trade_date="2026-08-28", expiry="16-10-2026",
                 strike="60", right="C"):
    return make_trade(trade_id, ticker, "OPTION", side, quantity, price,
                       trade_date, expiry, strike, right)


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


def test_options_with_same_underlying_and_side_are_not_confused():
    """Two different option contracts (different strikes) on the same
    ticker/side/quantity must NOT be matched to each other via the
    composite-key fallback - that would silently hide a real break
    (wrong strike booked) as a false clean match."""
    broker = [
        make_option("T0001", ticker="ASTS", strike="60", price=550.0),
        make_option("T0002", ticker="ASTS", strike="65", price=610.0),
    ]
    custodian = [
        # both trade_ids intentionally scrambled so this only resolves
        # via the composite key, not the trade_id fast path
        make_option("X0001", ticker="ASTS", strike="60", price=550.0),
        make_option("X0002", ticker="ASTS", strike="65", price=610.0),
    ]
    breaks, matched = reconcile(broker, custodian)
    # Should be 4 breaks total: both broker trades unmatched (custodian
    # ids don't line up and composite key differs only by trade_id, which
    # isn't part of the key) - the key point is nothing gets silently
    # cross-matched between the two different strikes.
    assert not any(
        b["break_type"] == "QUANTITY_MISMATCH" or b["break_type"] == "PRICE_MISMATCH"
        for b in breaks
    ), "a $60 strike and a $65 strike must never be compared as if they were the same contract"


def test_option_matched_via_composite_key_flags_id_mismatch():
    """If trade_id is corrupted but strike/expiry/right/ticker/side/qty all
    match, the engine still flags that the reference IDs didn't line up
    (useful in its own right - two systems disagreeing on a trade's
    reference is worth a note) rather than declaring a silent clean match."""
    b = make_option("T0001", strike="60")
    c = make_option("T9999", strike="60")  # id corrupted, everything else identical
    breaks, matched = reconcile([b], [c])
    assert len(breaks) == 1
    assert "via ticker/side/qty only" in breaks[0]["detail"]


def test_zero_price_trade_uses_absolute_not_relative_tolerance():
    """A free/promo share booked at price 0 must not divide by zero -
    should fall back to an absolute cent-level tolerance instead."""
    b = make_trade("T0001", price=0.0)
    c = make_trade("T0001", price=0.0)
    breaks, matched = reconcile([b], [c])
    assert breaks == []

    c_diff = make_trade("T0001", price=0.02)
    breaks2, _ = reconcile([b], [c_diff])
    assert break_types(breaks2) == ["PRICE_MISMATCH"]


def test_no_trade_silently_dropped():
    """Every trade on either side must end up either matched or in the
    breaks list - nothing should vanish."""
    broker = [make_trade("T0001"), make_trade("T0002", ticker="MSFT")]
    custodian = [make_trade("T0001")]
    breaks, matched = reconcile(broker, custodian)
    accounted_for = set(matched) | {b["trade_id"] for b in breaks}
    assert "T0001" in accounted_for
    assert "T0002" in accounted_for
