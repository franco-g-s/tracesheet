"""The multiples stage: P/E, EV/EBIT, EV/EBITDA, FCF yield, P/B and dividend yield.

Every multiple is set against the latest annual period. Per-share and cash-flow inputs are
the metrics stage's own values for that year (diluted EPS, free cash flow, book value per
share, dividend per share, net debt), so a multiple and the measure it divides by follow one
convention. Market capitalisation is the price times year-end shares outstanding; enterprise
value is market capitalisation + net debt (financial debt + lease liabilities - cash and
equivalents) + non-controlling interests.

A zero or negative denominator, or a missing input, gives ``NotMeaningful`` with the reason.
A negative numerator is a result, not an error: negative free cash flow is a negative yield.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time
from decimal import Decimal

from tracesheet.model import (
    LineItemName,
    Metrics,
    MetricValue,
    Money,
    Multiples,
    Normalized,
    NotMeaningful,
    PriceObservation,
    Traced,
    Unit,
)
from tracesheet.normalize.rates import YearRates, find_rates
from tracesheet.provenance import convert, observed, total

L = LineItemName

MULTIPLE_KEYS: tuple[str, ...] = (
    "pe",
    "ev_ebit",
    "ev_ebitda",
    "fcf_yield",
    "pb",
    "dividend_yield",
)
"""Every multiple, in the sheet's order."""

NO_RATE = "no exchange rate"


def _magnitude(node: Traced) -> Decimal:
    value = node.value
    if isinstance(value, Money):
        return value.amount
    assert isinstance(value, Decimal)
    return value


def _over(
    numerator: MetricValue, numerator_label: str, denominator: MetricValue, denominator_label: str
) -> MetricValue:
    """``numerator ÷ denominator``, carrying either side's reason when it has no value."""
    if isinstance(numerator, NotMeaningful):
        return NotMeaningful(reason=f"{numerator_label}: {numerator.reason}")
    if isinstance(denominator, NotMeaningful):
        return NotMeaningful(reason=f"{denominator_label}: {denominator.reason}")
    if _magnitude(denominator) <= 0:
        return NotMeaningful(reason=f"{denominator_label} is zero or negative")
    return numerator / denominator


def _price_leaf(price: PriceObservation) -> Traced:
    """The close as an observed leaf. It is dated by the close, not by when it was fetched,
    so the same close gives the same trail on every run."""
    listing = price.listing
    return observed(
        price.close,
        Unit.PER_SHARE,
        what=f"closing price of {listing.ticker} on {listing.venue}",
        source=price.source,
        observed_at=datetime.combine(price.date, time(), tzinfo=UTC),
    )


def compute_multiples(
    normalized: Normalized,
    metrics: Metrics,
    price: PriceObservation | None,
    rates: Sequence[YearRates] = (),
) -> Multiples | None:
    """The multiples for one close, or ``None`` when there is no price or no annual period.

    A price in another currency than the reporting one is converted at the closing rate of
    the ``YearRates`` for the price date's calendar year; the caller supplies the rate on
    the price date there. Without such a rate every figure that needs the price is
    "no exchange rate".
    """
    if price is None or not normalized.years:
        return None
    latest = normalized.years[-1]
    year = next((y for y in metrics.years if y.fiscal_year == latest.fiscal_year), None)
    if year is None:
        msg = f"the metrics have no values for the latest fiscal year, {latest.fiscal_year}"
        raise ValueError(msg)
    leaf = _price_leaf(price)

    rate: Traced | None = None
    if price.close.currency is not normalized.currency:
        found = find_rates(rates, price.close.currency, normalized.currency, price.date.year)
        if found is None:
            undefined = NotMeaningful(reason=NO_RATE)
            return Multiples(
                price=leaf,
                price_date=price.date,
                fiscal_year=latest.fiscal_year,
                market_cap=undefined,
                enterprise_value=undefined,
                values=dict.fromkeys(MULTIPLE_KEYS, undefined),
            )
        rate = found.closing
    per_share = leaf if rate is None else convert(leaf, rate)

    def line(name: LineItemName) -> MetricValue:
        figure = latest.line(name)
        if figure is None:
            return NotMeaningful(reason=f"{name.value.replace('_', ' ')} not filed")
        return figure

    shares = line(L.SHARES_OUTSTANDING)
    market_cap: MetricValue = shares if isinstance(shares, NotMeaningful) else per_share * shares
    enterprise_value = _enterprise_value(
        market_cap, year.values["net_debt"], line(L.NON_CONTROLLING_INTERESTS)
    )
    v: Mapping[str, MetricValue] = year.values
    values = {
        "pe": _over(per_share, "price", v["eps_diluted"], "diluted EPS"),
        "ev_ebit": _over(enterprise_value, "enterprise value", v["ebit"], "EBIT"),
        "ev_ebitda": _over(enterprise_value, "enterprise value", line(L.EBITDA), "EBITDA"),
        "fcf_yield": _over(v["fcf"], "free cash flow", market_cap, "market capitalisation"),
        "pb": _over(per_share, "price", v["bvps"], "book value per share"),
        "dividend_yield": _over(v["dps"], "dividend per share", per_share, "price"),
    }
    assert tuple(values) == MULTIPLE_KEYS
    return Multiples(
        price=leaf,
        price_date=price.date,
        fiscal_year=latest.fiscal_year,
        exchange_rate=rate,
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        values=values,
    )


def _enterprise_value(
    market_cap: MetricValue, net_debt: MetricValue, minorities: MetricValue
) -> MetricValue:
    """Market capitalisation + net debt + non-controlling interests."""
    if isinstance(market_cap, NotMeaningful):
        return NotMeaningful(reason=f"market capitalisation: {market_cap.reason}")
    if isinstance(net_debt, NotMeaningful):
        return NotMeaningful(reason=f"net debt: {net_debt.reason}")
    if isinstance(minorities, NotMeaningful):
        return minorities
    return total(market_cap, net_debt, minorities)
