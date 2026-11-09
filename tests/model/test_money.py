from decimal import Decimal

import pytest

from tracesheet.model import Currency, CurrencyMismatchError, Money, ShareCount


def test_money_adds_in_one_currency() -> None:
    a = Money(amount=Decimal("1.10"), currency=Currency.CHF)
    assert (a + a).amount == Decimal("2.20")


def test_money_refuses_mixed_currencies() -> None:
    with pytest.raises(CurrencyMismatchError):
        Money(amount=Decimal(1), currency=Currency.CHF) + Money(
            amount=Decimal(1), currency=Currency.EUR
        )


def test_money_refuses_a_float() -> None:
    with pytest.raises(ValueError, match="Decimal"):
        Money(amount=1.1, currency=Currency.CHF)  # type: ignore[arg-type]


def test_money_divided_by_money_is_a_bare_ratio() -> None:
    a = Money.parse("50", Currency.CHF)
    b = Money.parse("200", Currency.CHF)
    assert a / b == Decimal("0.25")


def test_share_count_is_not_money() -> None:
    assert str(ShareCount(count=Decimal(120))) == "120 shares"
