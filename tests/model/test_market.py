from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from tracesheet.model import CompanyId, Currency, Listing, Money, ShareCount
from tracesheet.model.market import (
    RATIO_ACTIONS,
    SHARE_BASIS_ACTIONS,
    ActionKind,
    CorporateAction,
    PriceObservation,
    RightsTerms,
    SharesKind,
    SharesObservation,
)

LISTING = Listing(venue="SIX", ticker="ACME", isin="CH0012221716")
NOW = datetime(2026, 1, 5, tzinfo=UTC)


def _chf(amount: str) -> Money:
    return Money.parse(amount, Currency.CHF)


def _action(**over: Any) -> CorporateAction:
    data: dict[str, Any] = {
        "company_id": CompanyId("acme"),
        "kind": ActionKind.SPLIT,
        "ex_date": date(2020, 6, 1),
        "new_shares": 5,
        "old_shares": 1,
        "source": "issuer notice",
    }
    return CorporateAction(**{**data, **over})


def _price(**over: Any) -> PriceObservation:
    data: dict[str, Any] = {
        "company_id": CompanyId("acme"),
        "listing": LISTING,
        "date": date(2026, 1, 2),
        "close": _chf("100"),
        "source": "vendor",
        "retrieved_at": NOW,
    }
    return PriceObservation(**{**data, **over})


def test_split_exposes_its_ratio() -> None:
    action = _action()
    assert action.ratio == Decimal(5)
    assert action.effective == date(2020, 6, 1)


def test_ratio_is_absent_without_both_numbers() -> None:
    assert _action(kind=ActionKind.DELISTING, new_shares=None, old_shares=None).ratio is None


def test_split_must_make_more_shares() -> None:
    with pytest.raises(ValidationError, match="more shares"):
        _action(new_shares=1, old_shares=5)


def test_reverse_split_must_make_fewer_shares() -> None:
    with pytest.raises(ValidationError, match="fewer shares"):
        _action(kind=ActionKind.REVERSE_SPLIT)
    assert _action(kind=ActionKind.REVERSE_SPLIT, new_shares=1, old_shares=10).ratio == Decimal(
        "0.1"
    )


def test_ratio_action_without_a_ratio_is_refused() -> None:
    with pytest.raises(ValidationError, match="carries a ratio"):
        _action(new_shares=None, old_shares=None)


def test_ratio_must_be_positive_and_complete() -> None:
    with pytest.raises(ValidationError, match="both"):
        _action(old_shares=None)
    with pytest.raises(ValidationError, match="positive"):
        _action(old_shares=0)


def test_dividend_carries_an_amount_and_no_ratio() -> None:
    dividend = _action(
        kind=ActionKind.DIVIDEND, amount=_chf("2.50"), new_shares=None, old_shares=None
    )
    assert dividend.amount == _chf("2.50")
    with pytest.raises(ValidationError, match="amount per share"):
        _action(kind=ActionKind.DIVIDEND, new_shares=None, old_shares=None)
    with pytest.raises(ValidationError, match="amount per share"):
        _action(kind=ActionKind.DIVIDEND, amount=_chf("2.50"))


def test_share_basis_action_carries_no_amount() -> None:
    with pytest.raises(ValidationError, match="no amount"):
        _action(amount=_chf("1"))


def test_class_unification_names_the_surviving_class() -> None:
    with pytest.raises(ValidationError, match="into_class"):
        _action(kind=ActionKind.CLASS_UNIFICATION)
    ok = _action(kind=ActionKind.CLASS_UNIFICATION, into_class="registered", share_class="series_b")
    assert ok.into_class == "registered"
    with pytest.raises(ValidationError, match="only a class unification"):
        _action(into_class="registered")


def test_rights_terms_only_on_a_rights_issue() -> None:
    terms = RightsTerms(offered_shares=1, held_shares=4, subscription_price=_chf("80"))
    with pytest.raises(ValidationError, match="only a rights issue"):
        _action(rights=terms)
    issue = _action(kind=ActionKind.RIGHTS_ISSUE, new_shares=None, old_shares=None, rights=terms)
    assert issue.rights == terms


def test_rights_terms_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="positive"):
        RightsTerms(offered_shares=0, held_shares=4, subscription_price=_chf("80"))
    with pytest.raises(ValidationError, match="positive"):
        RightsTerms(offered_shares=1, held_shares=4, subscription_price=_chf("0"))


def test_rights_issue_needs_a_factor_or_terms_once_confirmed() -> None:
    with pytest.raises(ValidationError, match="printed factor or its terms"):
        _action(kind=ActionKind.RIGHTS_ISSUE, new_shares=None, old_shares=None, confirmed_by="x")
    with pytest.raises(ValidationError, match="printed factor is positive"):
        _action(
            kind=ActionKind.RIGHTS_ISSUE,
            new_shares=None,
            old_shares=None,
            printed_factor=Decimal(0),
        )


def test_action_sets() -> None:
    assert ActionKind.SPLIT in RATIO_ACTIONS
    assert ActionKind.RIGHTS_ISSUE in SHARE_BASIS_ACTIONS
    assert ActionKind.RIGHTS_ISSUE not in RATIO_ACTIONS


def test_corporate_action_has_no_review_fields() -> None:
    assert "proposed_by" not in CorporateAction.model_fields
    assert "proposal" not in CorporateAction.model_fields


def test_price_in_one_currency() -> None:
    assert _price(open=_chf("99")).open == _chf("99")
    with pytest.raises(ValidationError, match="in EUR"):
        _price(high=Money.parse("101", Currency.EUR))


def test_price_round_trips() -> None:
    p = _price()
    assert PriceObservation.model_validate_json(p.model_dump_json()) == p


def test_shares_observation_names_its_kind() -> None:
    obs = SharesObservation(
        company_id=CompanyId("acme"),
        date=date(2026, 1, 2),
        count=ShareCount(count=Decimal(1000)),
        kind=SharesKind.OUTSTANDING,
        source="vendor",
        retrieved_at=NOW,
    )
    assert obs.kind is SharesKind.OUTSTANDING
