"""Share-basis normalization, against Acme's 1:2 split of 2 June 2025 from its actions file."""

from datetime import UTC, date, datetime
from decimal import Decimal

from conftest import Loaded
from tracesheet.model import (
    ActionKind,
    AdjustmentKind,
    CompanyId,
    CorporateAction,
    Currency,
    LineItemName,
    Money,
    Normalized,
    Observed,
    PriceObservation,
    RightsTerms,
    ShareCount,
)
from tracesheet.normalize import normalize
from tracesheet.normalize.shares import describe, factor

AS_OF = datetime(2026, 6, 30, tzinfo=UTC)
BEFORE_SPLIT = datetime(2025, 4, 1, tzinfo=UTC)

ORIGINAL_EPS_2024 = Decimal("7.54")
ORIGINAL_SHARES_2024 = Decimal("10000000")


def _eps(n: Normalized, year: int) -> Decimal:
    line = n.year(year).line(LineItemName.EPS_DILUTED)
    assert line is not None and isinstance(line.value, Money)
    return line.value.amount


def _shares(n: Normalized, year: int) -> Decimal:
    line = n.year(year).line(LineItemName.SHARES_DILUTED)
    assert line is not None and isinstance(line.value, ShareCount)
    return line.value.count


def _notes(n: Normalized, kind: AdjustmentKind) -> list[str]:
    return [a.detail for a in n.adjustments if a.kind is kind]


def test_split_restates_per_share_and_counts(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF, actions=acme.actions)
    assert _eps(n, 2024) == ORIGINAL_EPS_2024 / 2
    assert _shares(n, 2024) == ORIGINAL_SHARES_2024 * 2
    # amounts of money are never touched
    revenue = n.year(2024).line(LineItemName.REVENUE)
    assert revenue is not None and revenue.value == Money(
        amount=Decimal("820000000"), currency=Currency.CHF
    )


def test_a_report_filed_after_the_split_is_already_on_the_new_basis(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF, actions=acme.actions)
    assert _eps(n, 2025) == Decimal("4.32")
    assert _shares(n, 2025) == Decimal("20000000")


def test_the_factor_is_a_leaf_naming_the_split_and_its_page(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, AS_OF, actions=acme.actions)
    eps = n.year(2024).line(LineItemName.EPS_DILUTED)
    assert eps is not None
    leaves = [o for o in eps.sources() if isinstance(o, Observed)]
    assert len(leaves) == 1
    assert leaves[0].what == "factor 2, 1:2 split of 2 June 2025 (Acme Annual Report 2025, p. 88)"
    assert leaves[0].source.startswith("Acme Annual Report 2025, p. 88, PDF p. 90, sha256 ")
    (note,) = _notes(n, AdjustmentKind.SHARE_BASIS)
    assert note == (
        "FY2024: one per-share line divided by 2 and one share count multiplied by 2, for the "
        "1:2 split of 2 June 2025 (Acme Annual Report 2025, p. 88). Figures are on the share "
        "basis of 30 June 2026."
    )


def test_a_split_after_as_of_changes_nothing(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records, BEFORE_SPLIT, actions=acme.actions)
    assert _eps(n, 2024) == ORIGINAL_EPS_2024
    assert _shares(n, 2024) == ORIGINAL_SHARES_2024
    assert _notes(n, AdjustmentKind.SHARE_BASIS) == []


def test_an_action_without_confirmation_is_not_used(acme: Loaded) -> None:
    unconfirmed = acme.actions[0].model_copy(update={"confirmed_by": None})
    n = normalize(acme.company, acme.records, AS_OF, actions=(unconfirmed,))
    assert _eps(n, 2024) == ORIGINAL_EPS_2024


def _rights(
    rights: RightsTerms | None = None, printed_factor: Decimal | None = None
) -> CorporateAction:
    return CorporateAction(
        company_id=CompanyId("acme"),
        kind=ActionKind.RIGHTS_ISSUE,
        ex_date=date(2025, 6, 2),
        rights=rights,
        printed_factor=printed_factor,
        source="Acme Annual Report 2025, p. 90",
        confirmed_by="acme/actions.toml",
    )


TERMS = RightsTerms(
    offered_shares=1,
    held_shares=1,
    subscription_price=Money(amount=Decimal("40"), currency=Currency.CHF),
)


def test_a_rights_issue_factor_comes_from_the_cum_rights_close(acme: Loaded) -> None:
    # one new share per share held at 40, last cum-rights close 60: ex-rights price
    # (60 + 40) / 2 = 50, factor 60 / 50 = 1.2
    close = PriceObservation(
        company_id=acme.company.id,
        listing=acme.company.listing,
        date=date(2025, 5, 30),
        close=Money(amount=Decimal("60"), currency=Currency.CHF),
        source="test feed",
        retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    n = normalize(
        acme.company, acme.records[:1], AS_OF, actions=(_rights(rights=TERMS),), prices=(close,)
    )
    assert _shares(n, 2024) == Decimal("12000000.0")
    assert _eps(n, 2024).quantize(Decimal("0.0001")) == Decimal("6.2833")
    eps = n.year(2024).line(LineItemName.EPS_DILUTED)
    assert eps is not None
    whats = {o.what for o in eps.sources() if isinstance(o, Observed)}
    assert "last cum-rights close 2025-05-30" in whats


def test_a_rights_issue_with_a_printed_factor_uses_it(acme: Loaded) -> None:
    action = _rights(printed_factor=Decimal("1.25"))
    found = factor(action)
    assert found is not None and found.display == "1.25"
    n = normalize(acme.company, acme.records[:1], AS_OF, actions=(action,))
    assert _shares(n, 2024) == Decimal("12500000.00")


def test_a_rights_issue_without_a_close_is_left_as_filed_and_said_so(acme: Loaded) -> None:
    n = normalize(acme.company, acme.records[:1], AS_OF, actions=(_rights(rights=TERMS),))
    assert _shares(n, 2024) == ORIGINAL_SHARES_2024
    (note,) = _notes(n, AdjustmentKind.SHARE_BASIS_NOT_ADJUSTED)
    assert note.startswith("FY2024: eps_diluted, shares_diluted not adjusted for the rights issue")


def test_an_inexact_ratio_is_kept_as_two_whole_numbers(acme: Loaded) -> None:
    consolidation = acme.actions[0].model_copy(
        update={"kind": ActionKind.REVERSE_SPLIT, "new_shares": 2, "old_shares": 3}
    )
    found = factor(consolidation)
    assert found is not None and found.single is None and found.display == "2/3"
    assert describe(consolidation).startswith("3:2 reverse split of 2 June 2025")


def test_an_action_between_period_end_and_filing_is_pointed_out(acme: Loaded) -> None:
    early = acme.actions[0].model_copy(update={"ex_date": date(2025, 2, 3)})
    n = normalize(acme.company, acme.records[:1], AS_OF, actions=(early,))
    # the report was filed after the split, so its per-share line is already on the new basis
    assert _eps(n, 2024) == ORIGINAL_EPS_2024
    (note,) = _notes(n, AdjustmentKind.SHARE_BASIS_WINDOW)
    assert "took effect after the period ended (31 December 2024)" in note


def test_several_live_share_classes_are_left_as_filed(acme: Loaded) -> None:
    two_classes = acme.company.model_copy(update={"share_classes": ("registered", "participation")})
    n = normalize(two_classes, acme.records, AS_OF, actions=acme.actions)
    assert _eps(n, 2024) == ORIGINAL_EPS_2024
    assert len(_notes(n, AdjustmentKind.MULTIPLE_SHARE_CLASSES)) == 1


def test_a_spin_off_is_recorded_never_adjusted(acme: Loaded) -> None:
    spin = CorporateAction(
        company_id=acme.company.id,
        kind=ActionKind.SPIN_OFF,
        ex_date=date(2025, 6, 2),
        source="Acme Annual Report 2025, p. 91",
        confirmed_by="acme/actions.toml",
    )
    n = normalize(acme.company, acme.records, AS_OF, actions=(spin,))
    assert _eps(n, 2024) == ORIGINAL_EPS_2024
    assert len(_notes(n, AdjustmentKind.SPIN_OFF)) == 1
