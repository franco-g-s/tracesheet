"""Kühne+Nagel, typed in from its annual and half-year reports: every year loads and ties out."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from tracesheet.evaluate import evaluate
from tracesheet.model import ActionKind, CompanyId, Currency, Money, PeriodKind
from tracesheet.providers.hand_loaded import HandLoaded
from tracesheet.providers.reconcile import reconcile
from tracesheet.storage import Store

ROOT = Path(__file__).parents[2] / "data" / "companies"
KN = CompanyId("kuehne-nagel")

ONE_PRINTED_UNIT = Money(amount=Decimal("1000000"), currency=Currency.CHF)
"""Every Kühne+Nagel record is printed in CHF millions, and each printed line is rounded on
its own, so two figures one printed unit apart still count as equal."""


def test_twenty_one_fiscal_years_load_and_tie_out() -> None:
    records = HandLoaded(ROOT).financial_records(KN)
    annual = {r.period.end.year for r in records if r.period.kind is PeriodKind.ANNUAL}
    assert annual == set(range(2005, 2026))
    for record in records:
        assert reconcile(record, ONE_PRINTED_UNIT) == (), record.id


def test_every_line_has_a_page_and_a_label_unless_not_printed() -> None:
    for record in HandLoaded(ROOT).financial_records(KN):
        for item in record.line_items:
            assert item.page is not None, (record.id, item.name)
            assert item.not_printed or item.label, (record.id, item.name)


def test_the_2006_share_split_loads_from_its_registered_report() -> None:
    (split,) = HandLoaded(ROOT).actions(KN)
    assert split.kind is ActionKind.SPLIT
    assert split.ex_date == date(2006, 5, 2)
    assert (split.new_shares, split.old_shares) == (5, 1)


def test_the_full_evaluation_survives_storage(tmp_path: Path) -> None:
    # Twenty-one years exercise what the small fixture cannot: growth over spans of years,
    # calculated lines, restatements and the 2006 split, all through the store and back.
    evaluation = evaluate(ROOT, KN, datetime(2026, 11, 9, tzinfo=UTC), None)
    store = Store(tmp_path)
    assert store.load(store.save(evaluation)) == evaluation
