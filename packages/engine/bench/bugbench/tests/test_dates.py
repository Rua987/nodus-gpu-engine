from datetime import date

from dates import days_between, is_leap


def test_century_divisible_by_400_is_leap():
    assert is_leap(2000) is True


def test_plain_century_is_not_leap():
    assert is_leap(1900) is False


def test_ordinary_leap_year():
    assert is_leap(2024) is True


def test_days_between_ignores_order():
    assert days_between(date(2026, 3, 4), date(2026, 3, 1)) == 3


def test_days_between_same_day_is_zero():
    assert days_between(date(2026, 3, 1), date(2026, 3, 1)) == 0
