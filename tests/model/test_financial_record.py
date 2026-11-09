from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tracesheet.model import (
    DEFINITION,
    STATEMENT,
    CompanyId,
    Currency,
    FinancialRecord,
    FiscalPeriod,
    LineItem,
    LineItemName,
    Money,
    PeriodKind,
    RecordId,
    Source,
    readable_name,
)
from tracesheet.provenance import Filed, Unit, trace

SHA = "ab" * 32


def record(*items: LineItem) -> FinancialRecord:
    return FinancialRecord(
        id=RecordId("acme-fy2024"),
        company_id=CompanyId("acme"),
        period=FiscalPeriod(start=date(2024, 1, 1), end=date(2024, 12, 31), kind=PeriodKind.ANNUAL),
        filed_at=datetime(2025, 3, 1, tzinfo=UTC),
        source=Source(provider="hand-loaded", reference="Annual Report 2024", sha256=SHA),
        line_items=items,
    )


REVENUE = LineItem(
    name=LineItemName.REVENUE,
    value=Money(amount=Decimal("1000"), currency=Currency.CHF),
    label="Net turnover",
    page=42,
)


def test_a_duplicate_line_item_is_refused() -> None:
    with pytest.raises(ValueError, match="appears twice"):
        record(REVENUE, REVENUE)


def test_trace_returns_a_filed_origin_with_document_page_and_quote() -> None:
    traced = trace(record(REVENUE), LineItemName.REVENUE)
    assert traced.unit is Unit.AMOUNT
    origin = traced.origin
    assert isinstance(origin, Filed)
    assert origin.source.reference == "Annual Report 2024"
    assert origin.source.sha256 == SHA
    assert origin.page == 42
    assert origin.label == "Net turnover"


def test_a_record_filed_before_its_period_ends_is_refused() -> None:
    with pytest.raises(ValueError, match="before the period ended"):
        FinancialRecord(
            id=RecordId("x"),
            company_id=CompanyId("acme"),
            period=FiscalPeriod(
                start=date(2024, 1, 1), end=date(2024, 12, 31), kind=PeriodKind.ANNUAL
            ),
            filed_at=datetime(2024, 6, 1, tzinfo=UTC),
            source=Source(provider="hand-loaded", reference="r"),
            line_items=(REVENUE,),
        )


def test_every_line_has_a_statement_and_a_definition() -> None:
    assert set(STATEMENT) == set(LineItemName)
    assert set(DEFINITION) == set(LineItemName)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("special_dividend_per_share", "special dividend per share"),
        ("non_controlling_interests", "non-controlling interests"),
        ("non_current_borrowings", "non-current borrowings"),
        ("ebitda", "EBITDA"),
        ("eps_diluted", "diluted EPS"),
        ("revenue", "revenue"),
    ],
)
def test_a_line_item_has_a_readable_name(name: str, text: str) -> None:
    assert readable_name(LineItemName(name)) == text
