"""How figures are written: rounding, signs, units and the amount precision boundary."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tracesheet.metrics.catalogue import Kind
from tracesheet.model import Currency, Money, Traced, Unit
from tracesheet.model.traced import observed
from tracesheet.report import format as fmt

WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def ratio(text: str) -> Traced:
    return observed(Decimal(text), Unit.RATIO, what="r", source="test", observed_at=WHEN)


def amount(text: str, unit: Unit = Unit.AMOUNT) -> Traced:
    return observed(
        Money.parse(text, Currency.CHF), unit, what="a", source="test", observed_at=WHEN
    )


@pytest.mark.parametrize(
    ("value", "decimals", "text"),
    [
        ("0.125", 2, "0.12"),  # a tie rounds to the even digit
        ("0.135", 2, "0.14"),
        ("-0.04", 1, "0.0"),  # minus zero is shown as zero
        ("-1234.5", 1, fmt.MINUS + "1,234.5"),
        ("1234567", 0, "1,234,567"),
    ],
)
def test_number(value: str, decimals: int, text: str) -> None:
    assert fmt.number(Decimal(value), decimals) == text


def test_a_unit_mismatch_is_refused() -> None:
    with pytest.raises(fmt.FormatError):
        fmt.cell(ratio("0.5"), Kind.AMOUNT, Currency.CHF)
    with pytest.raises(fmt.FormatError):
        fmt.cell(amount("10", Unit.PER_SHARE), Kind.AMOUNT, Currency.CHF)


@pytest.mark.parametrize(
    ("kind", "cell", "plain"),
    [(Kind.PERCENT, "24.9", "24.9%"), (Kind.MULTIPLE, "0.2", "0.2" + fmt.TIMES)],
)
def test_a_ratio_reads_as_its_kind(kind: Kind, cell: str, plain: str) -> None:
    value = ratio("0.249")
    assert fmt.cell(value, kind, Currency.CHF) == cell
    assert fmt.plain(value, kind) == plain


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("99940000", "99.9"),  # below a hundred million: one decimal
        ("99960000", "100.0"),  # still below by the exact value, so still one decimal
        ("100000000", "100"),  # from a hundred million: whole millions
        ("-250400000", fmt.MINUS + "250"),
    ],
)
def test_amounts_switch_to_whole_millions_at_a_hundred_million(value: str, text: str) -> None:
    assert fmt.cell(amount(value), Kind.AMOUNT, Currency.CHF) == text


def test_a_row_shares_one_precision() -> None:
    row = [amount("51000000"), amount("646000000")]
    places = fmt.amount_decimals(row)

    assert places == 0
    assert [fmt.cell(f, Kind.AMOUNT, Currency.CHF, places) for f in row] == ["51", "646"]


def test_money_in_another_currency_names_it() -> None:
    eur = observed(
        Money.parse("12.5", Currency.EUR), Unit.PER_SHARE, what="p", source="t", observed_at=WHEN
    )
    assert fmt.cell(eur, Kind.PER_SHARE, Currency.CHF) == "EUR 12.50"
