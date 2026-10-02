import pytest

from shop import apply_discount, cart_total, parse_qty


def test_discount_takes_a_percentage():
    assert apply_discount(200, 15) == 170.0


def test_no_discount_keeps_the_price():
    assert apply_discount(99.99, 0) == 99.99


def test_discount_out_of_range_is_refused():
    with pytest.raises(ValueError):
        apply_discount(10, 120)


def test_cart_total_counts_every_item():
    items = [("pen", 1.5, 2), ("pad", 4.0, 1), ("ink", 2.25, 4)]
    assert cart_total(items) == 16.0


def test_empty_cart_is_free():
    assert cart_total([]) == 0.0


def test_quantity_tolerates_spaces():
    assert parse_qty(" 3 ") == 3


def test_quantity_refuses_words():
    with pytest.raises(ValueError):
        parse_qty("three")
