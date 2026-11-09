"""The metrics stage: every catalogue measure for every year, each traced or marked n/m.

Two passes. The first computes each year's measures from that year's figures and, for the
measures on average balances, the figures of the fiscal year before it. The second computes
growth from the first pass's values: year on year for the catalogue's growth measures, and
compound annual growth over 5 and 10 years ending in the latest year.

Every value is built with traced arithmetic, so it carries its trail back to the filed
lines. A value that cannot be computed is ``NotMeaningful`` with a reason: a missing input
names the line, and a zero or negative denominator names the denominator. Nothing is
clamped or imputed.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import wraps

from tracesheet.metrics.catalogue import CAGR_KEYS, CAGR_SPANS, CATALOGUE
from tracesheet.model import (
    Currency,
    LineItemName,
    Money,
    Normalized,
    PeriodFigures,
    ShareCount,
    Traced,
    Unit,
)
from tracesheet.model.metrics import Metrics, MetricValue, NotMeaningful, YearMetrics
from tracesheet.model.traced import growth_rate, mean, observed, percent_change

L = LineItemName

IFRS_16_EFFECTIVE = date(2019, 1, 1)
"""IFRS 16 put leases on the balance sheet for periods beginning on or after this date. A
period that began earlier, with no lease line filed, recognised no lease liability."""


class _Undefined(Exception):  # noqa: N818 - a control-flow signal, caught inside this module
    """Raised inside a measure when it has no meaningful value; becomes ``NotMeaningful``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Context:
    """What one year's measures read: the year, the fiscal year before it when the series
    has it, and the reporting currency."""

    current: PeriodFigures
    prior: PeriodFigures | None
    currency: Currency


# --- Reading lines and guarding arithmetic ---


def _magnitude(node: Traced) -> Decimal:
    value = node.value
    if isinstance(value, Money):
        return value.amount
    if isinstance(value, ShareCount):
        return value.count
    assert isinstance(value, Decimal)
    return value


def _line(figures: PeriodFigures, name: LineItemName) -> Traced:
    line = figures.line(name)
    if line is None:
        raise _Undefined(f"{name.value.replace('_', ' ')} not filed")
    return line


def _ratio(numerator: Traced, denominator: Traced, denominator_label: str) -> Traced:
    """``numerator ÷ denominator``, undefined when the denominator is zero or negative."""
    if _magnitude(denominator) <= 0:
        raise _Undefined(f"{denominator_label} is zero or negative")
    return numerator / denominator


def _average(ctx: Context, balance: Callable[[Context, PeriodFigures], Traced]) -> Traced:
    """The mean of the opening and closing balance: last year's close and this year's."""
    if ctx.prior is None:
        raise _Undefined("no opening balance")
    return mean(balance(ctx, ctx.prior), balance(ctx, ctx.current))


# --- Balances several measures share ---


def _financial_debt(_: Context, figures: PeriodFigures) -> Traced:
    filed = figures.line(L.FINANCIAL_DEBT)
    if filed is not None:
        return filed
    # Normalization usually solves the total from the pair; this covers a series without it.
    non_current = figures.line(L.NON_CURRENT_BORROWINGS)
    current = figures.line(L.CURRENT_BORROWINGS)
    if non_current is not None and current is not None:
        return non_current + current
    raise _Undefined("financial debt not filed")


def _lease_liabilities(ctx: Context, figures: PeriodFigures) -> Traced:
    filed = figures.line(L.LEASE_LIABILITIES)
    if filed is not None:
        return filed
    # Normalization usually solves the total from the pair; this covers a series without it.
    non_current = figures.line(L.NON_CURRENT_LEASE_LIABILITIES)
    current = figures.line(L.CURRENT_LEASE_LIABILITIES)
    if non_current is not None and current is not None:
        return non_current + current
    if non_current is None and current is None and figures.period.start < IFRS_16_EFFECTIVE:
        return observed(
            Money(amount=Decimal(0), currency=ctx.currency),
            Unit.AMOUNT,
            what="no lease liability recognised before IFRS 16",
            source="accounting standard",
            # The balance-sheet date, so the leaf, and every id above it, is the same on
            # every run.
            observed_at=datetime.combine(figures.period.end, time(), tzinfo=UTC),
        )
    raise _Undefined("lease liabilities not filed")


def _net_debt_at(ctx: Context, figures: PeriodFigures) -> Traced:
    return (
        _financial_debt(ctx, figures)
        + _lease_liabilities(ctx, figures)
        - _line(figures, L.CASH_AND_EQUIVALENTS)
    )


def _invested_capital(ctx: Context, figures: PeriodFigures) -> Traced:
    return _line(figures, L.TOTAL_EQUITY) + _net_debt_at(ctx, figures)


def _equity_attributable(_: Context, figures: PeriodFigures) -> Traced:
    return _line(figures, L.TOTAL_EQUITY) - _line(figures, L.NON_CONTROLLING_INTERESTS)


def _total_assets(_: Context, figures: PeriodFigures) -> Traced:
    return _line(figures, L.TOTAL_ASSETS)


def _outflow(figures: PeriodFigures, name: LineItemName, missing: str | None = None) -> Traced:
    """A cash outflow, held as a positive magnitude. A negative one is refused rather than
    flipped: it means the line was typed against the convention, and the page should be read."""
    line = figures.line(name)
    if line is None:
        raise _Undefined(missing or f"{name.value.replace('_', ' ')} not filed")
    if _magnitude(line) < 0:
        raise _Undefined(f"{name.value.replace('_', ' ')} filed as negative; expected an outflow")
    return line


def _capex_at(figures: PeriodFigures) -> Traced:
    """Both purchase lines, each a positive outflow. Intangible purchases count as zero only
    when the record declares the line not printed: that arrives as a filed zero."""
    intangible = _outflow(
        figures, L.INTANGIBLE_CAPITAL_EXPENDITURE, missing="intangible purchases not filed"
    )
    return _outflow(figures, L.CAPITAL_EXPENDITURE) + intangible


def _fcf_at(figures: PeriodFigures) -> Traced:
    return _line(figures, L.OPERATING_CASH_FLOW) - _capex_at(figures)


def _nopat(figures: PeriodFigures) -> Traced:
    """EBIT * (1 - tax / profit before tax), written as EBIT * ((PBT - tax) / PBT) so that
    no bare constant enters the trail."""
    pbt = _line(figures, L.PROFIT_BEFORE_TAX)
    retained = _ratio(pbt - _line(figures, L.INCOME_TAX_EXPENSE), pbt, "profit before tax")
    return _line(figures, L.EBIT) * retained


# --- The measures: one small function each ---

Measure = Callable[[Context], MetricValue]


def _measure(compute: Callable[[Context], Traced]) -> Measure:
    """Turn a measure that raises ``_Undefined`` into one that returns ``NotMeaningful``."""

    @wraps(compute)
    def guarded(ctx: Context) -> MetricValue:
        try:
            return compute(ctx)
        except _Undefined as undefined:
            return NotMeaningful(reason=undefined.reason)

    return guarded


def _filed(name: LineItemName) -> Measure:
    return _measure(lambda ctx: _line(ctx.current, name))


def _over_revenue(name: LineItemName) -> Measure:
    return _measure(lambda ctx: _ratio(_line(ctx.current, name), _revenue(ctx), "revenue"))


def _revenue(ctx: Context) -> Traced:
    return _line(ctx.current, L.REVENUE)


@_measure
def _roe(ctx: Context) -> Traced:
    average = _average(ctx, _equity_attributable)
    owners = _line(ctx.current, L.NET_INCOME_ATTRIBUTABLE_TO_OWNERS)
    return _ratio(owners, average, "average equity attributable to shareholders")


@_measure
def _roa(ctx: Context) -> Traced:
    average = _average(ctx, _total_assets)
    return _ratio(_line(ctx.current, L.NET_INCOME), average, "average total assets")


@_measure
def _roic(ctx: Context) -> Traced:
    average = _average(ctx, _invested_capital)
    return _ratio(_nopat(ctx.current), average, "average invested capital")


@_measure
def _capex(ctx: Context) -> Traced:
    return _capex_at(ctx.current)


@_measure
def _fcf(ctx: Context) -> Traced:
    return _fcf_at(ctx.current)


@_measure
def _fcf_conversion(ctx: Context) -> Traced:
    return _ratio(_fcf_at(ctx.current), _line(ctx.current, L.NET_INCOME), "net income")


@_measure
def _capex_to_revenue(ctx: Context) -> Traced:
    return _ratio(_capex_at(ctx.current), _revenue(ctx), "revenue")


@_measure
def _net_debt(ctx: Context) -> Traced:
    return _net_debt_at(ctx, ctx.current)


@_measure
def _net_debt_to_ebitda(ctx: Context) -> Traced:
    return _ratio(_net_debt_at(ctx, ctx.current), _line(ctx.current, L.EBITDA), "EBITDA")


@_measure
def _equity_ratio(ctx: Context) -> Traced:
    total_assets = _line(ctx.current, L.TOTAL_ASSETS)
    return _ratio(_line(ctx.current, L.TOTAL_EQUITY), total_assets, "total assets")


@_measure
def _current_ratio(ctx: Context) -> Traced:
    liabilities = _line(ctx.current, L.CURRENT_LIABILITIES)
    return _ratio(_line(ctx.current, L.CURRENT_ASSETS), liabilities, "current liabilities")


@_measure
def _payout_ratio(ctx: Context) -> Traced:
    eps = _line(ctx.current, L.EPS_DILUTED)
    return _ratio(_line(ctx.current, L.DIVIDEND_PER_SHARE), eps, "diluted EPS")


@_measure
def _diluted_share_change(ctx: Context) -> Traced:
    if ctx.prior is None:
        raise _Undefined("no prior year")
    prior = _line(ctx.prior, L.SHARES_DILUTED)
    if _magnitude(prior) <= 0:
        raise _Undefined("prior-year diluted shares is zero or negative")
    return percent_change(prior, _line(ctx.current, L.SHARES_DILUTED))


@_measure
def _special_dps(ctx: Context) -> Traced:
    special = ctx.current.line(L.SPECIAL_DIVIDEND_PER_SHARE)
    if special is not None:
        return special
    if ctx.current.line(L.DIVIDEND_PER_SHARE) is None:
        raise _Undefined("no dividend filed")
    raise _Undefined("special_dividend_per_share not filed")


@_measure
def _buybacks(ctx: Context) -> Traced:
    return _outflow(ctx.current, L.SHARE_REPURCHASES)


@_measure
def _fcf_per_share(ctx: Context) -> Traced:
    shares = _line(ctx.current, L.SHARES_DILUTED)
    return _ratio(_fcf_at(ctx.current), shares, "diluted shares")


@_measure
def _bvps(ctx: Context) -> Traced:
    shares = _line(ctx.current, L.SHARES_OUTSTANDING)
    equity = _equity_attributable(ctx, ctx.current)
    return _ratio(equity, shares, "shares outstanding")


MEASURES: Mapping[str, Measure] = {
    "revenue": _filed(L.REVENUE),
    "ebit": _filed(L.EBIT),
    "net_income": _filed(L.NET_INCOME),
    "gross_margin": _over_revenue(L.GROSS_PROFIT),
    "ebitda_margin": _over_revenue(L.EBITDA),
    "ebit_margin": _over_revenue(L.EBIT),
    "net_margin": _over_revenue(L.NET_INCOME),
    "roe": _roe,
    "roa": _roa,
    "roic": _roic,
    "operating_cash_flow": _filed(L.OPERATING_CASH_FLOW),
    "capex": _capex,
    "fcf": _fcf,
    "fcf_conversion": _fcf_conversion,
    "capex_to_revenue": _capex_to_revenue,
    "net_debt": _net_debt,
    "net_debt_to_ebitda": _net_debt_to_ebitda,
    "equity_ratio": _equity_ratio,
    "current_ratio": _current_ratio,
    "dps": _filed(L.DIVIDEND_PER_SHARE),
    "special_dps": _special_dps,
    "payout_ratio": _payout_ratio,
    "buybacks": _buybacks,
    "diluted_share_change": _diluted_share_change,
    "eps_diluted": _filed(L.EPS_DILUTED),
    "fcf_per_share": _fcf_per_share,
    "bvps": _bvps,
}
"""Every catalogue measure that is not a growth rate, by key. Growth rates are computed in
the second pass, from these values."""


# --- Growth, from the first pass's values ---


def _label(key: str) -> str:
    """The measure's label as it reads mid-sentence: "net income", but "EBIT"."""
    label = next(m.label for m in CATALOGUE if m.key == key)
    return label[0].lower() + label[1:] if label[1:2].islower() else label


def _growth(start: MetricValue | None, end: MetricValue, key: str) -> MetricValue:
    """Year-on-year growth from last year's value to this year's."""
    if start is None:
        return NotMeaningful(reason="no prior year")
    if isinstance(start, NotMeaningful):
        return NotMeaningful(reason=f"prior year: {start.reason}")
    if isinstance(end, NotMeaningful):
        return end
    if _magnitude(start) <= 0:
        return NotMeaningful(reason=f"prior-year {_label(key)} is zero or negative")
    return percent_change(start, end)


def _compound(start: MetricValue, end: MetricValue, key: str, span: int) -> MetricValue:
    """Compound annual growth over ``span`` years; both ends must be positive."""
    for value, when in ((start, "starting"), (end, "latest")):
        if isinstance(value, NotMeaningful):
            return NotMeaningful(reason=f"{when} year: {value.reason}")
        if _magnitude(value) <= 0:
            return NotMeaningful(reason=f"{_label(key)} is zero or negative in the {when} year")
    assert isinstance(start, Traced) and isinstance(end, Traced)
    return growth_rate(start, end, years=span)


def _cagr(base: Mapping[int, Mapping[str, MetricValue]]) -> dict[str, dict[int, MetricValue]]:
    """Compound growth of each ``CAGR_KEYS`` measure over each span, ending in the latest
    year. The starting year must be in the series: a gap there is n/m, never bridged."""
    if not base:
        empty = NotMeaningful(reason="no annual figures")
        return {key: dict.fromkeys(CAGR_SPANS, empty) for key in CAGR_KEYS}
    latest = max(base)
    result: dict[str, dict[int, MetricValue]] = {key: {} for key in CAGR_KEYS}
    for span in CAGR_SPANS:
        start_year = base.get(latest - span)
        for key in CAGR_KEYS:
            if start_year is None:
                result[key][span] = NotMeaningful(reason=f"no figures for {latest - span}")
            else:
                result[key][span] = _compound(start_year[key], base[latest][key], key, span)
    return result


# --- The stage ---


def compute_metrics(normalized: Normalized) -> Metrics:
    """Every catalogue measure for every annual period, and compound growth."""
    by_year = {block.fiscal_year: block for block in normalized.years}
    base: dict[int, dict[str, MetricValue]] = {}
    for block in normalized.years:
        ctx = Context(
            current=block,
            prior=by_year.get(block.fiscal_year - 1),
            currency=normalized.currency,
        )
        base[block.fiscal_year] = {key: measure(ctx) for key, measure in MEASURES.items()}

    years: list[YearMetrics] = []
    for fiscal_year, values in base.items():
        prior = base.get(fiscal_year - 1)
        computed: dict[str, MetricValue] = {}
        for metric in CATALOGUE:
            if metric.growth_of is None:
                computed[metric.key] = values[metric.key]
                continue
            start = prior[metric.growth_of] if prior is not None else None
            computed[metric.key] = _growth(start, values[metric.growth_of], metric.growth_of)
        years.append(YearMetrics(fiscal_year=fiscal_year, values=computed))
    return Metrics(years=tuple(years), cagr=_cagr(base))
