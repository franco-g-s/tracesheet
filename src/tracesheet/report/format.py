"""How a figure is shown: rounded for the eye, from the exact decimal, never stored.

The stored value keeps every digit; the page rounds half to even (banker's rounding), so a
column of rounded figures does not drift upwards. Negative figures carry a true minus sign.
A table cell is a bare number, because its row states the unit once; ``plain`` writes the
unit out, for a figure that stands alone.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal

from tracesheet.metrics.catalogue import Kind
from tracesheet.model import Currency, Money, ShareCount, Traced, Unit
from tracesheet.model.units import ExchangeRate

MINUS = "−"
TIMES = "×"
MILLION = Decimal(1_000_000)
HUNDRED = Decimal(100)

_UNITS: dict[Kind, Unit] = {
    Kind.AMOUNT: Unit.AMOUNT,
    Kind.PER_SHARE: Unit.PER_SHARE,
    Kind.PERCENT: Unit.RATIO,
    Kind.MULTIPLE: Unit.RATIO,
    Kind.COUNT: Unit.COUNT,
}


class FormatError(ValueError):
    """A figure cannot be shown as the kind its measure declares."""


def number(value: Decimal, decimals: int) -> str:
    """``-1234.5`` at one decimal gives ``−1,234.5``, with a true minus sign."""
    rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        rounded = abs(rounded)
    text = f"{abs(rounded):,.{decimals}f}"
    return f"{MINUS}{text}" if rounded < 0 else text


def unit_caption(kind: Kind, currency: Currency) -> str:
    """The unit a row states once, so that its cells can be bare numbers."""
    return {
        Kind.AMOUNT: f"{currency.value} m",
        Kind.PER_SHARE: currency.value,
        Kind.PERCENT: "%",
        Kind.MULTIPLE: TIMES,
        Kind.COUNT: "m",
    }[kind]


def amount_decimals(figures: Iterable[Traced]) -> int:
    """One precision for a whole row of amounts, so its figures line up: whole millions
    once any of them reaches a hundred million, one decimal otherwise."""
    largest = max(
        (abs(f.value.amount) for f in figures if isinstance(f.value, Money)), default=Decimal(0)
    )
    return _amount_decimals(largest / MILLION)


def cell(figure: Traced, kind: Kind, currency: Currency, decimals: int | None = None) -> str:
    """A figure as a table cell, without its unit. A money figure in another currency than
    the row's names its own. ``decimals`` fixes an amount's precision, as for a whole row;
    by default it follows the figure's own size."""
    if figure.unit is not _UNITS[kind]:
        msg = f"a {figure.unit.value} figure cannot be shown as {kind.value}"
        raise FormatError(msg)
    value = figure.value
    if isinstance(value, Money):
        if kind is Kind.AMOUNT:
            millions = value.amount / MILLION
            places = decimals if decimals is not None else _amount_decimals(millions)
            text = number(millions, places)
        else:
            text = number(value.amount, 2)
        return text if value.currency is currency else f"{value.currency.value} {text}"
    if isinstance(value, ShareCount):
        return number(value.count / MILLION, 1)
    if isinstance(value, Decimal):
        return number(value * HUNDRED if kind is Kind.PERCENT else value, 1)
    msg = f"a {type(value).__name__} is not a table figure"
    raise FormatError(msg)


def plain(figure: Traced, kind: Kind | None = None) -> str:
    """A figure with its unit, to stand on its own: ``CHF 1,654 m``, ``24.9%``, ``14.2×``.

    ``kind`` tells a multiple from a percentage, which share one unit; without it a ratio
    reads as a percentage.
    """
    value = figure.value
    if isinstance(value, Money):
        if figure.unit is Unit.AMOUNT and abs(value.amount) >= MILLION:
            millions = value.amount / MILLION
            return f"{value.currency.value} {number(millions, _amount_decimals(millions))} m"
        return f"{value.currency.value} {number(value.amount, 2)}"
    if isinstance(value, ShareCount):
        return f"{number(value.count / MILLION, 3)} m shares"
    if isinstance(value, ExchangeRate):
        return f"1 {value.base.value} = {number(value.rate, 4)} {value.quote.value}"
    if kind is Kind.MULTIPLE:
        return f"{number(value, 1)}{TIMES}"
    return f"{number(value * HUNDRED, 1)}%"


def _amount_decimals(millions: Decimal) -> int:
    """Whole millions for large figures; one decimal below a hundred million, where a whole
    number would hide most of the figure."""
    return 0 if abs(millions) >= HUNDRED else 1
