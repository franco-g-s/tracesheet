"""Money and share counts.

Money is an exact decimal with a currency. It cannot be built from a float, cannot exist
without a currency, and cannot be mixed across currencies. Dividing money by money gives a
bare ratio, which is no longer money. Share counts are a separate type so a count can never
be added to an amount.
"""

from decimal import Decimal
from enum import StrEnum
from typing import overload

from tracesheet.model.base import Model


class Currency(StrEnum):
    """ISO 4217 codes. Add a line to widen; never accept a name or a lower-case variant."""

    CHF = "CHF"
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"


class CurrencyMismatchError(ValueError):
    """Two amounts in different currencies were combined or compared."""


class Money(Model):
    """An exact amount in one currency."""

    amount: Decimal
    currency: Currency

    @classmethod
    def parse(cls, text: str, currency: Currency) -> "Money":
        """Build from text — ``Money.parse("1234.50", Currency.CHF)`` — so no float is involved."""
        return cls(amount=Decimal(text), currency=currency)

    def _same_currency(self, other: "Money") -> None:
        if self.currency is not other.currency:
            msg = f"{self.currency} and {other.currency} cannot be combined"
            raise CurrencyMismatchError(msg)

    def __add__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    def __mul__(self, factor: Decimal) -> "Money":
        # Decimal itself refuses a float operand, so a float cannot get in this way either.
        return Money(amount=self.amount * factor, currency=self.currency)

    __rmul__ = __mul__

    @overload
    def __truediv__(self, divisor: "Money") -> Decimal: ...
    @overload
    def __truediv__(self, divisor: Decimal) -> "Money": ...
    def __truediv__(self, divisor: "Money | Decimal") -> "Money | Decimal":
        if isinstance(divisor, Money):
            self._same_currency(divisor)
            return self.amount / divisor.amount
        return Money(amount=self.amount / divisor, currency=self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._same_currency(other)
        return self.amount >= other.amount

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


class ShareCount(Model):
    """A number of shares. Not money: it has no currency and cannot be added to an amount."""

    count: Decimal

    def __add__(self, other: "ShareCount") -> "ShareCount":
        return ShareCount(count=self.count + other.count)

    def __sub__(self, other: "ShareCount") -> "ShareCount":
        return ShareCount(count=self.count - other.count)

    def __lt__(self, other: "ShareCount") -> bool:
        return self.count < other.count

    def __le__(self, other: "ShareCount") -> bool:
        return self.count <= other.count

    def __gt__(self, other: "ShareCount") -> bool:
        return self.count > other.count

    def __ge__(self, other: "ShareCount") -> bool:
        return self.count >= other.count

    def __str__(self) -> str:
        return f"{self.count} shares"
