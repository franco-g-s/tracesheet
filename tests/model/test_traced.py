from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tracesheet import provenance
from tracesheet.model import Currency, ExchangeRate, Money, Unit
from tracesheet.provenance import (
    ProvenanceError,
    Traced,
    Transform,
    convert,
    cross_rate,
    growth_rate,
    mean,
    observed,
    percent_change,
    total,
)

AT = datetime(2026, 1, 1, tzinfo=UTC)


def chf(x: str) -> Traced:
    # Each leaf names its own figure: two leaves with identical origins are one source.
    return observed(
        Money(amount=Decimal(x), currency=Currency.CHF),
        Unit.AMOUNT,
        what=x,
        source="test",
        observed_at=AT,
    )


def test_ratio_of_amounts_is_a_ratio_and_keeps_both_sources() -> None:
    r = chf("50") / chf("200")
    assert r.unit is Unit.RATIO and r.value == Decimal("0.25")
    assert len(r.sources()) == 2


def test_a_derived_node_must_recompute() -> None:
    r = chf("1") + chf("2")
    with pytest.raises(ValueError, match="does not recompute"):
        Traced(
            value=Money(amount=Decimal(4), currency=Currency.CHF),
            unit=Unit.AMOUNT,
            transform=r.transform,
            inputs=r.inputs,
        )


def test_cagr_over_years() -> None:
    g = growth_rate(chf("100"), chf("121"), years=2)
    assert isinstance(g.value, Decimal)
    assert g.value.quantize(Decimal("0.0001")) == Decimal("0.1000")


def test_ids_are_content_hashes() -> None:
    assert (chf("1") + chf("2")).id == (chf("1") + chf("2")).id


def test_total_mean_and_percent_change() -> None:
    assert total(chf("1"), chf("2"), chf("3")).value == Money.parse("6", Currency.CHF)
    assert mean(chf("1"), chf("2"), chf("3")).value == Money.parse("2", Currency.CHF)
    assert percent_change(chf("100"), chf("110")).value == Decimal("0.1")


def test_amount_plus_ratio_is_refused() -> None:
    with pytest.raises(ProvenanceError):
        _ = chf("1") + chf("1") / chf("2")


def test_convert_through_a_cross_rate() -> None:
    def rate(r: str, quote: Currency) -> Traced:
        return observed(
            ExchangeRate(rate=Decimal(r), base=Currency.EUR, quote=quote),
            Unit.EXCHANGE_RATE,
            what=f"{quote} per EUR",
            source="test",
            observed_at=AT,
        )

    chf_per_usd = cross_rate(rate("0.95", Currency.CHF), rate("1.25", Currency.USD))
    usd = observed(
        Money.parse("100", Currency.USD), Unit.AMOUNT, what="u", source="test", observed_at=AT
    )
    assert convert(usd, chf_per_usd).value == Money.parse("76", Currency.CHF)


def test_only_arithmetic_operations_remain() -> None:
    assert {t.value for t in Transform} == {
        "add",
        "subtract",
        "negate",
        "multiply",
        "divide",
        "total",
        "mean",
        "percent_change",
        "growth_rate",
        "convert",
        "cross_rate",
    }
    assert {name for name in provenance.__all__ if name[0].islower()} == {
        "convert",
        "cross_rate",
        "growth_rate",
        "mean",
        "observed",
        "percent_change",
        "total",
        "trace",
    }
