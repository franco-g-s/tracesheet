from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import Loaded
from tracesheet.model import AdjustmentKind, Currency, LineItemName, Money, PeriodFigures
from tracesheet.model.traced import trace
from tracesheet.normalize import normalize, standardize

AS_OF = datetime(2026, 6, 30, tzinfo=UTC)


def test_missing_subtotal_is_derived_and_marked(acme: Loaded) -> None:
    # neither Acme report prints total_liabilities_and_equity; standardize solves it
    y = normalize(acme.company, acme.records, AS_OF).year(2025)
    assert y.is_calculated(LineItemName.TOTAL_LIABILITIES_AND_EQUITY)
    line = y.line(LineItemName.TOTAL_LIABILITIES_AND_EQUITY)
    assert line is not None
    assert line.value == Money(amount=Decimal("968400000"), currency=Currency.CHF)
    assert not y.is_calculated(LineItemName.TOTAL_ASSETS)


def test_each_calculation_is_stated(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF)
    calculated = [a for a in n.adjustments if a.kind is AdjustmentKind.CALCULATED]
    assert [a.period.fiscal_year for a in calculated if a.period] == [2024, 2025]
    assert "total_liabilities_and_equity calculated as" in calculated[0].detail


def test_nothing_to_solve_returns_the_block_unchanged(acme: Loaded) -> None:
    record = acme.records[0]
    block = PeriodFigures(
        period=record.period, figures={LineItemName.REVENUE: trace(record, LineItemName.REVENUE)}
    )
    out, note = standardize(block, "FY2024")
    assert out is block
    assert note is None


def test_a_part_is_solved_from_its_total(acme: Loaded) -> None:
    record = acme.records[0]
    names = (LineItemName.REVENUE, LineItemName.GROSS_PROFIT)
    block = PeriodFigures(period=record.period, figures={n: trace(record, n) for n in names})
    out, note = standardize(block, "FY2024")
    cost = out.line(LineItemName.COST_OF_SALES)
    assert cost is not None and out.is_calculated(LineItemName.COST_OF_SALES)
    assert cost.value == Money(amount=Decimal("492000000"), currency=record.currency)
    assert note is not None and "FY2024: cost_of_sales calculated as" in note.detail


def test_a_printed_line_is_never_also_calculated(acme: Loaded) -> None:
    record = acme.records[0]
    revenue = trace(record, LineItemName.REVENUE)
    with pytest.raises(ValidationError, match="never also calculated"):
        PeriodFigures(
            period=record.period,
            figures={LineItemName.REVENUE: revenue},
            calculated={LineItemName.REVENUE: revenue},
        )
