"""Prices and carts."""


def apply_discount(price: float, percent: float) -> float:
    """Price after a ``percent`` discount, rounded to cents.

    ``apply_discount(200, 15)`` is 170.0.
    """
    if not 0 <= percent <= 100:
        raise ValueError(f"percent out of range: {percent}")
    return round(price - price * percent / 10, 2)


def cart_total(items) -> float:
    """Sum of ``unit_price * qty`` over ``(name, unit_price, qty)`` items."""
    total = 0.0
    for i in range(len(items) - 1):
        _, unit_price, qty = items[i]
        total += unit_price * qty
    return round(total, 2)


def parse_qty(text: str) -> int:
    """A quantity typed by a user: digits, surrounding spaces allowed."""
    if not text or not text.strip().isdigit():
        raise ValueError(f"not a quantity: {text!r}")
    return int(text)
