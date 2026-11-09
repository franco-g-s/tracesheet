import re
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from tracesheet.model import (
    CompanyId,
    Currency,
    FinancialRecord,
    FiscalPeriod,
    LineItem,
    LineItemName,
    Money,
    PeriodKind,
    RecordId,
    ShareCount,
    Source,
)
from tracesheet.providers.hand_loaded import HandLoaded
from tracesheet.providers.reconcile import reconcile

CHF_1_5 = Money(amount=Decimal("1.5"), currency=Currency.CHF)


def test_fixture_ties_out(acme_root: Path) -> None:
    for r in HandLoaded(acme_root).financial_records(CompanyId("acme")):
        assert reconcile(r, Money(amount=Decimal("1.5"), currency=Currency.CHF)) == ()


def test_unbalanced_record_is_reported(acme_root: Path, tmp_path: Path) -> None:
    # +100 CHF on total assets: inside the loader's own tolerance (one printed unit, a
    # million), so the file still loads, but outside a tolerance of CHF 1.5.
    root = tmp_path / "companies"
    shutil.copytree(acme_root, root)
    path = root / "acme" / "fy2025.toml"
    pattern = re.compile(r'(name = "total_assets"\nvalue = ")([0-9.]+)(")')
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    assert match is not None
    bumped = Decimal(match.group(2)) + Decimal(100) / Decimal(1_000_000)
    path.write_text(pattern.sub(rf"\g<1>{bumped}\g<3>", text, count=1), encoding="utf-8")

    records = HandLoaded(root).financial_records(CompanyId("acme"))
    fy2025 = next(r for r in records if r.period.end.year == 2025)
    failures = reconcile(fy2025, CHF_1_5)
    assert len(failures) == 1
    assert "total_assets" in failures[0]


def _record(*items: tuple[LineItemName, Money | ShareCount]) -> FinancialRecord:
    return FinancialRecord(
        id=RecordId("fy2025"),
        company_id=CompanyId("test"),
        period=FiscalPeriod(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            kind=PeriodKind.ANNUAL,
        ),
        filed_at=datetime(2026, 3, 1, tzinfo=UTC),
        source=Source(provider="test", reference="test"),
        line_items=tuple(LineItem(name=name, value=value) for name, value in items),
    )


def _chf(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.CHF)


def test_part_larger_than_its_whole_is_reported() -> None:
    record = _record(
        (LineItemName.CASH_AND_EQUIVALENTS, _chf("120")),
        (LineItemName.CURRENT_ASSETS, _chf("100")),
    )
    (failure,) = reconcile(record, CHF_1_5)
    assert "cash_and_equivalents" in failure
    assert "exceeds" in failure


def test_subtotal_that_does_not_sum_is_reported() -> None:
    record = _record(
        (LineItemName.REVENUE, _chf("100")),
        (LineItemName.COST_OF_SALES, _chf("60")),
        (LineItemName.GROSS_PROFIT, _chf("45")),
    )
    (failure,) = reconcile(record, CHF_1_5)
    assert failure.startswith("gross_profit")


def test_difference_within_tolerance_ties() -> None:
    record = _record(
        (LineItemName.REVENUE, _chf("100")),
        (LineItemName.COST_OF_SALES, _chf("60")),
        (LineItemName.GROSS_PROFIT, _chf("41")),
    )
    assert reconcile(record, CHF_1_5) == ()


def test_missing_member_skips_the_identity() -> None:
    record = _record(
        (LineItemName.TOTAL_ASSETS, _chf("100")), (LineItemName.TOTAL_EQUITY, _chf("40"))
    )
    assert reconcile(record, CHF_1_5) == ()


def test_eps_that_the_share_count_does_not_reproduce_is_reported() -> None:
    record = _record(
        (LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS, _chf("10000000")),
        (LineItemName.EPS_DILUTED, _chf("1.00")),
        (LineItemName.SHARES_DILUTED, ShareCount(count=Decimal("1000000"))),
    )
    (failure,) = reconcile(record, CHF_1_5)
    assert failure.startswith("eps_diluted")


def test_eps_that_matches_ties() -> None:
    record = _record(
        (LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS, _chf("10000000")),
        (LineItemName.EPS_DILUTED, _chf("10.00")),
        (LineItemName.SHARES_DILUTED, ShareCount(count=Decimal("1000000"))),
    )
    assert reconcile(record, CHF_1_5) == ()
