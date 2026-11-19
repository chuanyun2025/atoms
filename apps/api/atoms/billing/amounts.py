"""Convert between ledger units and human-readable credits."""

SCALE = 1_000_000


def ceil_credit_units(raw_units: int) -> int:
    """Round a positive cost up to a whole credit."""
    return ((max(0, raw_units) + SCALE - 1) // SCALE) * SCALE


def amount(units: int) -> str:
    sign = "-" if units < 0 else ""
    whole, fraction = divmod(abs(units), SCALE)
    if fraction:
        return f"{sign}{whole}.{fraction:06d}".rstrip("0")
    return f"{sign}{whole}"
