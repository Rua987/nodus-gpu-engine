"""Calendar arithmetic."""
from datetime import date


def is_leap(year: int) -> bool:
    """Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_between(a: date, b: date) -> int:
    """Number of days separating two dates, whichever comes first."""
    return abs((b - a).days)
