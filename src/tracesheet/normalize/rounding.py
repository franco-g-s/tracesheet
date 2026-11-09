"""When two prints of one figure are the same figure.

A report printed in whole millions cannot say 0.7; it says 1, or 2 when a part is adjusted so
its printed total foots. A difference within the coarser print's rounding is not
information, so normalization keeps an original figure against a rounded re-print of it.
"""

from decimal import Decimal

from tracesheet.model import Money, ShareCount

ROUNDING_BAND = Decimal("1.5")
"""How many units of the coarser print two figures may differ by and still be one figure:
half a unit for ordinary rounding, one more for a part adjusted so its printed total foots."""


def within_rounding(
    first: Money | ShareCount,
    first_precision: Decimal | None,
    second: Money | ShareCount,
    second_precision: Decimal | None,
) -> bool:
    """Whether two prints of one figure differ by no more than the coarser print's rounding.
    False when either precision is unknown or the units differ: then they are compared as
    exact figures."""
    if first_precision is None or second_precision is None:
        return False
    if isinstance(first, Money) and isinstance(second, Money):
        if first.currency != second.currency:
            return False
        difference = abs(first.amount - second.amount)
    elif isinstance(first, ShareCount) and isinstance(second, ShareCount):
        difference = abs(first.count - second.count)
    else:
        return False
    return difference <= ROUNDING_BAND * max(first_precision, second_precision)
