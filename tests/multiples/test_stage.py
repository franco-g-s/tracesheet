"""Price multiples: one closing price set against the latest fiscal year, each traced or n/m."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tracesheet.metrics.stage import compute_metrics
from tracesheet.model import (
    COUNT_LINES,
    PER_SHARE_LINES,
    CompanyId,
    Currency,
    ExchangeRate,
    FiscalPeriod,
    LineItemName,
    Listing,
    MetricValue,
    Money,
    Multiples,
    Normalized,
    NotMeaningful,
    Observed,
    PeriodFigures,
    PeriodKind,
    PriceObservation,
    ShareCount,
    Traced,
    Unit,
)
from tracesheet.multiples.stage import MULTIPLE_KEYS, compute_multiples
from tracesheet.provenance import observed

L = LineItemName
WHEN = datetime(2026, 1, 1, tzinfo=UTC)
LISTING = Listing(venue="SIX", ticker="ACME", isin="CH0025238863")

LATEST: dict[LineItemName, str] = {
    L.REVENUE: "10000",
    L.EBITDA: "2250",
    L.EBIT: "1500",
    L.NET_INCOME: "1050",
    L.NET_INCOME_ATTRIBUTABLE_TO_OWNERS: "1000",
    L.EPS_DILUTED: "10",
    L.DIVIDEND_PER_SHARE: "4",
    L.OPERATING_CASH_FLOW: "2000",
    L.CAPITAL_EXPENDITURE: "600",
    L.INTANGIBLE_CAPITAL_EXPENDITURE: "400",
    L.CASH_AND_EQUIVALENTS: "2000",
    L.FINANCIAL_DEBT: "3000",
    L.LEASE_LIABILITIES: "1000",
    L.TOTAL_EQUITY: "10500",
    L.NON_CONTROLLING_INTERESTS: "500",
    L.SHARES_DILUTED: "100",
    L.SHARES_OUTSTANDING: "100",
}
"""Price 200 and 100 shares make a market cap of 20,000; EV = 20,000 + 3,000 + 1,000 + 500
- 2,000 = 22,500. FCF = 2,000 - (600 + 400) = 1,000. Book value per share = (10,500 - 500)
÷ 100 = 100."""


def without(name: LineItemName) -> dict[LineItemName, str]:
    return {k: v for k, v in LATEST.items() if k is not name}


def leaf(name: LineItemName, text: str, year: int) -> Traced:
    what = f"{name.value} FY{year}"
    if name in COUNT_LINES:
        return observed(
            ShareCount(count=Decimal(text)), Unit.COUNT, what=what, source="test", observed_at=WHEN
        )
    unit = Unit.PER_SHARE if name in PER_SHARE_LINES else Unit.AMOUNT
    return observed(
        Money.parse(text, Currency.CHF), unit, what=what, source="test", observed_at=WHEN
    )


def make_normalized(years: dict[int, dict[LineItemName, str]]) -> Normalized:
    return Normalized(
        company_id=CompanyId("acme"),
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        currency=Currency.CHF,
        years=tuple(
            PeriodFigures(
                period=FiscalPeriod(
                    start=date(year, 1, 1), end=date(year, 12, 31), kind=PeriodKind.ANNUAL
                ),
                figures={name: leaf(name, text, year) for name, text in lines.items()},
            )
            for year, lines in sorted(years.items())
        ),
        used=(),
    )


def price(close: str = "200", currency: Currency = Currency.CHF) -> PriceObservation:
    return PriceObservation(
        company_id=CompanyId("acme"),
        listing=LISTING,
        date=date(2026, 3, 13),
        close=Money.parse(close, currency),
        source="test exchange close",
        retrieved_at=datetime(2026, 3, 14, 9, 0, tzinfo=UTC),
    )


def run(
    lines: dict[LineItemName, str] | None = None,
    observation: PriceObservation | None = None,
    rate: Traced | None = None,
) -> Multiples:
    normalized = make_normalized({2025: LATEST if lines is None else lines})
    result = compute_multiples(
        normalized, compute_metrics(normalized), observation or price(), rate
    )
    assert result is not None
    return result


def amount(v: MetricValue) -> Decimal:
    assert isinstance(v, Traced), v
    if isinstance(v.value, Money):
        return v.value.amount
    assert isinstance(v.value, Decimal)
    return v.value


def reason(v: MetricValue) -> str:
    assert isinstance(v, NotMeaningful), v
    return v.reason


def usd_rate(base: Currency = Currency.USD) -> Traced:
    """0.80 CHF per USD, observed on the price date."""
    return observed(
        ExchangeRate(rate=Decimal("0.80"), base=base, quote=Currency.CHF),
        Unit.EXCHANGE_RATE,
        what=f"ECB reference rate CHF/{base.value}",
        source="ECB reference rate",
        observed_at=datetime(2026, 3, 13, 14, 15, tzinfo=UTC),
    )


# --- Known answers ---


def test_pe_is_price_over_diluted_eps() -> None:
    assert amount(run().values["pe"]) == Decimal(20)


def test_market_cap_is_price_times_year_end_shares_outstanding() -> None:
    m = run()
    assert amount(m.market_cap) == Decimal(20000)
    assert isinstance(m.market_cap, Traced) and m.market_cap.unit is Unit.AMOUNT


def test_enterprise_value_adds_debt_leases_minorities_and_subtracts_cash() -> None:
    assert amount(run().enterprise_value) == Decimal(22500)


def test_ev_multiples() -> None:
    v = run().values
    assert amount(v["ev_ebit"]) == Decimal(15)
    assert amount(v["ev_ebitda"]) == Decimal(10)


def test_fcf_yield_pb_and_dividend_yield() -> None:
    v = run().values
    assert amount(v["fcf_yield"]) == Decimal("0.05")
    assert amount(v["pb"]) == Decimal(2)
    assert amount(v["dividend_yield"]) == Decimal("0.02")


def test_every_multiple_is_present_in_order() -> None:
    assert tuple(run().values) == MULTIPLE_KEYS
    assert MULTIPLE_KEYS == ("pe", "ev_ebit", "ev_ebitda", "fcf_yield", "pb", "dividend_yield")
    assert all(amount(v) > 0 for v in run().values.values())


def test_net_cash_puts_enterprise_value_below_market_cap() -> None:
    m = run({**LATEST, L.CASH_AND_EQUIVALENTS: "10000"})
    assert amount(m.enterprise_value) == Decimal(14500)
    assert amount(m.enterprise_value) < amount(m.market_cap)


def test_set_against_the_latest_fiscal_year() -> None:
    older = {**LATEST, L.EPS_DILUTED: "5"}
    normalized = make_normalized({2024: older, 2025: LATEST})
    m = compute_multiples(normalized, compute_metrics(normalized), price())
    assert m is not None
    assert m.fiscal_year == 2025
    assert amount(m.values["pe"]) == Decimal(20)


# --- The price, its date and its source ---


def test_price_is_an_observed_per_share_leaf_naming_its_source() -> None:
    m = run()
    assert m.price.unit is Unit.PER_SHARE
    assert m.price.value == Money.parse("200", Currency.CHF)
    assert isinstance(m.price.origin, Observed)
    assert m.price.origin.source == "test exchange close"
    assert m.price_date == date(2026, 3, 13)
    assert m.exchange_rate is None


def test_price_leaf_is_dated_by_the_close_not_the_fetch() -> None:
    first = run(observation=price())
    later = price().model_copy(update={"retrieved_at": datetime(2026, 9, 1, tzinfo=UTC)})
    assert run(observation=later).price.id == first.price.id


def test_trail_reaches_the_price_and_the_filed_lines() -> None:
    pe = run().values["pe"]
    assert isinstance(pe, Traced)
    whats = {o.what for o in pe.sources() if isinstance(o, Observed)}
    assert "eps_diluted FY2025" in whats
    assert any("ACME" in w for w in whats)


def test_no_price_gives_none() -> None:
    normalized = make_normalized({2025: LATEST})
    assert compute_multiples(normalized, compute_metrics(normalized), None) is None


def test_no_annual_figures_gives_none() -> None:
    normalized = make_normalized({})
    assert compute_multiples(normalized, compute_metrics(normalized), price()) is None


# --- Undefined: non-positive denominators and missing inputs ---


def test_zero_ebitda_is_not_meaningful() -> None:
    v = run({**LATEST, L.EBITDA: "0"}).values
    assert reason(v["ev_ebitda"]) == "EBITDA is zero or negative"


def test_negative_eps_is_not_meaningful() -> None:
    assert reason(run({**LATEST, L.EPS_DILUTED: "-2"}).values["pe"]) == (
        "diluted EPS is zero or negative"
    )


def test_negative_ebit_and_book_value() -> None:
    v = run({**LATEST, L.EBIT: "-1", L.TOTAL_EQUITY: "400"}).values
    assert reason(v["ev_ebit"]) == "EBIT is zero or negative"
    assert reason(v["pb"]) == "book value per share is zero or negative"


def test_negative_fcf_gives_a_negative_yield_not_nm() -> None:
    v = run({**LATEST, L.OPERATING_CASH_FLOW: "500"}).values
    assert amount(v["fcf_yield"]) == Decimal("-0.025")


def test_zero_price_is_not_meaningful() -> None:
    v = run(observation=price("0")).values
    assert reason(v["dividend_yield"]) == "price is zero or negative"
    assert reason(v["fcf_yield"]) == "market capitalisation is zero or negative"


def test_missing_shares_outstanding_carries_through() -> None:
    lines = without(L.SHARES_OUTSTANDING)
    m = run(lines)
    assert reason(m.market_cap) == "shares outstanding not filed"
    assert reason(m.enterprise_value) == "market capitalisation: shares outstanding not filed"
    assert reason(m.values["ev_ebit"]) == (
        "enterprise value: market capitalisation: shares outstanding not filed"
    )
    assert amount(m.values["pe"]) == Decimal(20)


def test_missing_minorities_line_leaves_enterprise_value_nm() -> None:
    lines = without(L.NON_CONTROLLING_INTERESTS)
    m = run(lines)
    assert reason(m.enterprise_value) == "non controlling interests not filed"
    assert isinstance(m.market_cap, Traced)


def test_missing_numerator_metric_carries_its_reason() -> None:
    lines = without(L.DIVIDEND_PER_SHARE)
    assert reason(run(lines).values["dividend_yield"]) == (
        "dividend per share: dividend per share not filed"
    )


# --- Currency: the price's and the reporting currency ---


def test_foreign_price_converts_at_the_supplied_rate() -> None:
    # USD 250 at 0.80 CHF per USD is CHF 200: the same answers as a CHF 200 close.
    m = run(observation=price("250", Currency.USD), rate=usd_rate())
    assert m.price.value == Money.parse("250", Currency.USD)
    assert m.exchange_rate == usd_rate()
    assert amount(m.market_cap) == Decimal(20000)
    assert amount(m.enterprise_value) == Decimal(22500)
    assert amount(m.values["pe"]) == Decimal(20)
    pe = m.values["pe"]
    assert isinstance(pe, Traced)
    assert any(
        isinstance(o, Observed) and o.what == "ECB reference rate CHF/USD" for o in pe.sources()
    )


def test_foreign_price_without_a_rate_is_not_meaningful() -> None:
    m = run(observation=price("250", Currency.USD))
    assert m.exchange_rate is None
    assert reason(m.market_cap) == "no exchange rate"
    assert reason(m.enterprise_value) == "no exchange rate"
    assert all(reason(v) == "no exchange rate" for v in m.values.values())


def test_a_rate_for_another_pair_is_refused() -> None:
    with pytest.raises(ValueError, match="USD into CHF"):
        run(observation=price("250", Currency.USD), rate=usd_rate(base=Currency.EUR))


def test_a_rate_is_ignored_when_the_currencies_agree() -> None:
    m = run(rate=usd_rate())
    assert m.exchange_rate is None
    assert amount(m.values["pe"]) == Decimal(20)
