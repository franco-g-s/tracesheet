"""Units, and the rules for combining them — dimensional analysis for money.

An amount divided by a share count is a per-share amount; an amount plus a ratio is not a
number. The tables here are the whole rule set; adding a unit is an enumeration entry and
rows in the tables.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from tracesheet.model.base import Model
from tracesheet.model.money import Currency


class ProvenanceError(ValueError):
    """A traced number could not be built. The message says why, in plain words."""


class UnitMismatchError(ProvenanceError):
    """Two traced numbers cannot be combined this way — wrong units or currencies."""


class Unit(StrEnum):
    """What kind of quantity a traced number is."""

    AMOUNT = "amount"
    """A sum of money in a currency."""
    PER_SHARE = "per_share"
    """Money per one share."""
    RATIO = "ratio"
    """Dimensionless: a margin, a return, a multiple, a growth rate. Always a fraction."""
    COUNT = "count"
    """A number of shares."""
    EXCHANGE_RATE = "exchange_rate"
    """How many units of one currency one unit of another buys."""


class ExchangeRate(Model):
    """One ``base`` buys ``rate`` ``quote``: ``ExchangeRate(rate=0.9, base=USD, quote=CHF)``."""

    rate: Decimal
    base: Currency
    quote: Currency

    @model_validator(mode="after")
    def _sensible(self) -> "ExchangeRate":
        if self.rate <= 0:
            msg = "an exchange rate must be positive"
            raise ValueError(msg)
        if self.base is self.quote:
            msg = f"an exchange rate needs two different currencies, not {self.base} twice"
            raise ValueError(msg)
        return self

    def __str__(self) -> str:
        return f"{self.rate} {self.quote}/{self.base}"


MONEY_UNITS = frozenset({Unit.AMOUNT, Unit.PER_SHARE})

MULTIPLY: dict[tuple[Unit, Unit], Unit] = {
    (Unit.AMOUNT, Unit.RATIO): Unit.AMOUNT,
    (Unit.RATIO, Unit.AMOUNT): Unit.AMOUNT,
    (Unit.RATIO, Unit.RATIO): Unit.RATIO,
    (Unit.COUNT, Unit.PER_SHARE): Unit.AMOUNT,
    (Unit.PER_SHARE, Unit.COUNT): Unit.AMOUNT,
    (Unit.PER_SHARE, Unit.RATIO): Unit.PER_SHARE,
    (Unit.RATIO, Unit.PER_SHARE): Unit.PER_SHARE,
    (Unit.COUNT, Unit.RATIO): Unit.COUNT,
    (Unit.RATIO, Unit.COUNT): Unit.COUNT,
}
"""What multiplying two units gives. Exchange rates are applied only through ``convert``."""

DIVIDE: dict[tuple[Unit, Unit], Unit] = {
    (Unit.AMOUNT, Unit.AMOUNT): Unit.RATIO,
    (Unit.AMOUNT, Unit.COUNT): Unit.PER_SHARE,
    (Unit.AMOUNT, Unit.RATIO): Unit.AMOUNT,
    (Unit.AMOUNT, Unit.PER_SHARE): Unit.COUNT,
    (Unit.PER_SHARE, Unit.PER_SHARE): Unit.RATIO,
    (Unit.PER_SHARE, Unit.RATIO): Unit.PER_SHARE,
    (Unit.RATIO, Unit.RATIO): Unit.RATIO,
    (Unit.COUNT, Unit.COUNT): Unit.RATIO,
    (Unit.COUNT, Unit.RATIO): Unit.COUNT,
}
"""What dividing one unit by another gives."""
