from typing import Any

import pytest
from pydantic import ValidationError

from tracesheet.model import Company, CompanyId, Currency, Listing, MonthDay, ReportingStandard


def _company(**over: Any) -> Company:
    data: dict[str, Any] = {
        "id": CompanyId("acme"),
        "name": "Acme AG",
        "listing": Listing(venue="SIX", ticker="ACME", isin="CH0012221716"),
        "currency": Currency.CHF,
        "reporting_standard": ReportingStandard.IFRS,
        "domicile_country": "CH",
        "fiscal_year_end": MonthDay(month=12, day=31),
    }
    return Company(**{**data, **over})


def test_valid_company_round_trips_through_json() -> None:
    company = _company()
    assert Company.model_validate_json(company.model_dump_json()) == company
    assert company.share_classes == ("registered",)
    assert company.delisted_at is None


def test_bad_isin_check_digit_is_refused() -> None:
    with pytest.raises(ValidationError, match="check digit"):
        Listing(venue="SIX", ticker="ACME", isin="CH0012221717")


def test_malformed_isin_is_refused() -> None:
    with pytest.raises(ValidationError, match="not an ISIN"):
        Listing(venue="SIX", ticker="ACME", isin="not-an-isin")


def test_country_must_be_an_alpha2_code() -> None:
    with pytest.raises(ValidationError, match="alpha-2"):
        _company(domicile_country="Switzerland")


def test_share_classes_are_named_once_and_not_empty() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        _company(share_classes=())
    with pytest.raises(ValidationError, match="once each"):
        _company(share_classes=("registered", "registered"))
    with pytest.raises(ValidationError, match="has a name"):
        _company(share_classes=(" ",))


def test_reporting_standard_values() -> None:
    assert {s.value for s in ReportingStandard} == {"ifrs", "us_gaap", "swiss_gaap_fer"}
