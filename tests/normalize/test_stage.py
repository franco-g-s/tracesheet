from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import Loaded
from tracesheet.model import (
    Adjustment,
    AdjustmentKind,
    CompanyId,
    Currency,
    ExchangeRate,
    FinancialRecord,
    LineItemName,
    Money,
    Normalized,
    PeriodFigures,
    Unit,
)
from tracesheet.model.traced import observed, trace
from tracesheet.normalize import NormalizationError, YearRates, find_rates, normalize

AS_OF = datetime(2026, 6, 30, tzinfo=UTC)
"""After both Acme reports were filed (fy2025 on 9 March 2026)."""

BEFORE_FY2025 = datetime(2025, 4, 1, tzinfo=UTC)
"""After the fy2024 report (10 March 2025), before the fy2025 one."""


def _kinds(n: Normalized) -> set[AdjustmentKind]:
    return {a.kind for a in n.adjustments}


def _money(n: Normalized, year: int, name: LineItemName) -> Decimal:
    line = n.year(year).line(name)
    assert line is not None and isinstance(line.value, Money)
    return line.value.amount


def test_both_years_oldest_first(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF)
    assert n.fiscal_years == (2024, 2025)
    assert n.currency is Currency.CHF
    assert n.gaps == ()
    assert [ref.id for ref in n.used] == [r.id for r in acme.records]
    assert _money(n, 2025, LineItemName.REVENUE) == Decimal("905000000")


def test_only_figures_filed_by_as_of_are_used(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, BEFORE_FY2025)
    assert n.fiscal_years == (2024,)
    excluded = [a for a in n.adjustments if a.kind is AdjustmentKind.EXCLUDED_AFTER_AS_OF]
    assert len(excluded) == 1
    assert "2026-03-09" in excluded[0].detail


def test_nothing_filed_yet_gives_an_empty_series(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, datetime(2025, 1, 1, tzinfo=UTC))
    assert n.fiscal_years == ()
    assert n.latest_year_ending_by(datetime(2026, 1, 1, tzinfo=UTC).date()) is None


def test_latest_year_ending_by(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF)
    found = n.latest_year_ending_by(datetime(2025, 6, 30, tzinfo=UTC).date())
    assert found is not None and found.fiscal_year == 2024
    with pytest.raises(KeyError):
        n.year(2023)


def test_a_record_of_another_company_is_refused(acme: Loaded) -> None:
    stranger = acme.records[0].model_copy(update={"company_id": CompanyId("other")})
    with pytest.raises(NormalizationError, match="not acme"):
        normalize(acme.company, (stranger,), AS_OF)


def _restated(original: FinancialRecord, revenue: str, precision: str) -> FinancialRecord:
    """A later filing of the same period that re-prints revenue."""
    items = tuple(
        item.model_copy(
            update={
                "value": Money(amount=Decimal(revenue), currency=Currency.CHF),
                "precision": Decimal(precision),
            }
        )
        for item in original.line_items
        if item.name is LineItemName.REVENUE
    )
    return original.model_copy(
        update={
            "id": f"{original.id}-restated",
            "filed_at": datetime(2026, 3, 9, 6, tzinfo=UTC),
            "line_items": items,
            "restates": original.ref(),
        }
    )


def test_a_restated_line_comes_from_the_restatement(acme: Loaded) -> None:
    restated = _restated(acme.records[0], "830000000", "100000")
    n = normalize(acme.company, (*acme.records, restated), AS_OF)
    assert _money(n, 2024, LineItemName.REVENUE) == Decimal("830000000")
    assert _money(n, 2024, LineItemName.EBIT) == Decimal("98400000")
    assert {AdjustmentKind.RESTATEMENT_USED, AdjustmentKind.MIXED_FILINGS} <= _kinds(n)
    assert restated.ref() in n.used


def test_a_coarser_reprint_within_rounding_keeps_the_original(acme: Loaded) -> None:
    # 820.0 printed to a tenth of a million, re-printed as a whole 821 million
    restated = _restated(acme.records[0], "821000000", "1000000")
    n = normalize(acme.company, (*acme.records, restated), AS_OF)
    assert _money(n, 2024, LineItemName.REVENUE) == Decimal("820000000")
    assert AdjustmentKind.FINER_PRECISION_KEPT in _kinds(n)
    assert AdjustmentKind.RESTATEMENT_USED not in _kinds(n)


def _rate(rate: str) -> ExchangeRate:
    return ExchangeRate(rate=Decimal(rate), base=Currency.CHF, quote=Currency.EUR)


def _year_rates(year: int, average: str, closing: str) -> YearRates:
    at = datetime(year + 1, 1, 2, tzinfo=UTC)
    return YearRates(
        fiscal_year=year,
        average=observed(
            _rate(average), Unit.EXCHANGE_RATE, what="average", source="test", observed_at=at
        ),
        closing=observed(
            _rate(closing), Unit.EXCHANGE_RATE, what="closing", source="test", observed_at=at
        ),
    )


RATES = (_year_rates(2024, "1.05", "1.10"), _year_rates(2025, "1.02", "1.04"))


def test_flows_convert_at_the_average_and_balances_at_the_closing_rate(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF, target_currency=Currency.EUR, rates=RATES)
    assert n.currency is Currency.EUR
    revenue = n.year(2024).line(LineItemName.REVENUE)
    assert revenue is not None
    assert revenue.value == Money(amount=Decimal("861000000.00"), currency=Currency.EUR)
    assets = n.year(2024).line(LineItemName.TOTAL_ASSETS)
    assert assets is not None
    assert assets.value == Money(amount=Decimal("995500000.00"), currency=Currency.EUR)
    # the rate is a leaf of the converted figure's trail
    assert any(getattr(o, "what", None) == "average" for o in revenue.sources())
    assert AdjustmentKind.CURRENCY_CONVERTED in _kinds(n)


def test_a_missing_rate_is_an_error_not_a_guess(acme: Loaded) -> None:
    with pytest.raises(NormalizationError, match="fiscal 2025"):
        normalize(acme.company, acme.records, AS_OF, target_currency=Currency.EUR, rates=RATES[:1])


def test_find_rates_matches_pair_and_year() -> None:
    assert find_rates(RATES, Currency.CHF, Currency.EUR, 2025) is RATES[1]
    assert find_rates(RATES, Currency.EUR, Currency.CHF, 2025) is None
    assert find_rates(RATES, Currency.CHF, Currency.EUR, 2023) is None


def test_year_rates_refuse_mismatched_pairs() -> None:
    other = ExchangeRate(rate=Decimal("0.9"), base=Currency.USD, quote=Currency.CHF)
    at = datetime(2025, 1, 2, tzinfo=UTC)
    with pytest.raises(ValidationError, match="same currency pair"):
        YearRates(
            fiscal_year=2024,
            average=observed(_rate("1"), Unit.EXCHANGE_RATE, what="a", source="t", observed_at=at),
            closing=observed(other, Unit.EXCHANGE_RATE, what="c", source="t", observed_at=at),
        )


def test_a_figure_filed_after_as_of_cannot_be_held(acme: Loaded) -> None:
    late = acme.records[1]
    block = PeriodFigures(
        period=late.period, figures={LineItemName.REVENUE: trace(late, LineItemName.REVENUE)}
    )
    with pytest.raises(ValidationError, match="look-ahead"):
        Normalized(
            company_id=acme.company.id,
            as_of=BEFORE_FY2025,
            currency=Currency.CHF,
            years=(block,),
            used=(late.ref(),),
        )


def test_adjustments_read_in_period_order(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF, actions=acme.actions)
    ends = [a.period.end.isoformat() if a.period else "" for a in n.adjustments]
    assert ends == sorted(ends)
    assert all(isinstance(a, Adjustment) and a.detail for a in n.adjustments)
