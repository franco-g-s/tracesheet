"""A hand-built ``Normalized`` with known answers, for the metrics stage."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tracesheet.model import (
    PER_SHARE_LINES,
    CompanyId,
    Currency,
    FiscalPeriod,
    LineItemName,
    Money,
    Normalized,
    PeriodFigures,
    PeriodKind,
    ShareCount,
    Traced,
    Unit,
)
from tracesheet.model.financial_record import COUNT_LINES
from tracesheet.model.traced import observed

L = LineItemName

MakeNormalized = Callable[[dict[int, dict[LineItemName, str]]], Normalized]


def leaf(name: LineItemName, text: str, year: int) -> Traced:
    """An observed CHF leaf for one line of one year, so the trail stands without a filing.
    ``what`` names the line and the year, so equal figures in two years stay two leaves."""
    what = f"{name.value} FY{year}"
    when = datetime(2026, 1, 1, tzinfo=UTC)
    if name in COUNT_LINES:
        return observed(
            ShareCount(count=Decimal(text)), Unit.COUNT, what=what, source="test", observed_at=when
        )
    unit = Unit.PER_SHARE if name in PER_SHARE_LINES else Unit.AMOUNT
    return observed(
        Money.parse(text, Currency.CHF), unit, what=what, source="test", observed_at=when
    )


def make_normalized(years: dict[int, dict[LineItemName, str]]) -> Normalized:
    """One calendar fiscal year per key, each line an observed CHF leaf."""
    blocks = tuple(
        PeriodFigures(
            period=FiscalPeriod(
                start=date(year, 1, 1), end=date(year, 12, 31), kind=PeriodKind.ANNUAL
            ),
            figures={name: leaf(name, text, year) for name, text in lines.items()},
        )
        for year, lines in sorted(years.items())
    )
    return Normalized(
        company_id=CompanyId("acme"),
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        currency=Currency.CHF,
        years=blocks,
        used=(),
    )


FY2024: dict[LineItemName, str] = {
    L.REVENUE: "1000",
    L.GROSS_PROFIT: "400",
    L.EBITDA: "220",
    L.EBIT: "160",
    L.PROFIT_BEFORE_TAX: "150",
    L.INCOME_TAX_EXPENSE: "30",
    L.NET_INCOME: "120",
    L.NET_INCOME_ATTRIBUTABLE_TO_OWNERS: "110",
    L.EPS_DILUTED: "1.10",
    L.DIVIDEND_PER_SHARE: "0.55",
    L.OPERATING_CASH_FLOW: "400",
    L.CAPITAL_EXPENDITURE: "100",
    L.INTANGIBLE_CAPITAL_EXPENDITURE: "20",
    L.SHARE_REPURCHASES: "10",
    L.CASH_AND_EQUIVALENTS: "300",
    L.CURRENT_ASSETS: "900",
    L.CURRENT_LIABILITIES: "600",
    L.TOTAL_ASSETS: "2000",
    L.TOTAL_EQUITY: "900",
    L.NON_CONTROLLING_INTERESTS: "100",
    L.FINANCIAL_DEBT: "250",
    L.LEASE_LIABILITIES: "150",
    L.SHARES_DILUTED: "100",
    L.SHARES_OUTSTANDING: "100",
}
"""Invested capital 900 + 250 + 150 - 300 = 1000."""

FY2025: dict[LineItemName, str] = {
    L.REVENUE: "1100",
    L.GROSS_PROFIT: "462",
    L.EBITDA: "275",
    L.EBIT: "200",
    L.PROFIT_BEFORE_TAX: "160",
    L.INCOME_TAX_EXPENSE: "40",
    L.NET_INCOME: "120",
    L.NET_INCOME_ATTRIBUTABLE_TO_OWNERS: "115",
    L.EPS_DILUTED: "1.25",
    L.DIVIDEND_PER_SHARE: "0.50",
    L.SPECIAL_DIVIDEND_PER_SHARE: "0.20",
    L.OPERATING_CASH_FLOW: "500",
    L.CAPITAL_EXPENDITURE: "120",
    L.INTANGIBLE_CAPITAL_EXPENDITURE: "30",
    L.SHARE_REPURCHASES: "25",
    L.CASH_AND_EQUIVALENTS: "250",
    L.CURRENT_ASSETS: "1000",
    L.CURRENT_LIABILITIES: "800",
    L.TOTAL_ASSETS: "2200",
    L.TOTAL_EQUITY: "1000",
    L.NON_CONTROLLING_INTERESTS: "100",
    L.NON_CURRENT_BORROWINGS: "200",
    L.CURRENT_BORROWINGS: "100",
    L.NON_CURRENT_LEASE_LIABILITIES: "120",
    L.CURRENT_LEASE_LIABILITIES: "30",
    L.SHARES_DILUTED: "96",
    L.SHARES_OUTSTANDING: "95",
}
"""Invested capital 1000 + (200 + 100) + (120 + 30) - 250 = 1200, with debt and leases
filed only as their current and non-current halves."""


@pytest.fixture
def make() -> MakeNormalized:
    return make_normalized


@pytest.fixture
def n2() -> Normalized:
    """Two years, 2024 and 2025, with every input filed."""
    return make_normalized({2024: FY2024, 2025: FY2025})


@pytest.fixture
def loss_year() -> Normalized:
    """2025 is a loss before tax."""
    return make_normalized(
        {2024: FY2024, 2025: {**FY2025, L.PROFIT_BEFORE_TAX: "-10", L.INCOME_TAX_EXPENSE: "5"}}
    )
