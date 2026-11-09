"""Company identity: who a company is, where it is listed and how it reports.

Domicile (where it is incorporated) and listing venue (where its shares trade) are separate
fields on purpose: they coincide for many companies and diverge for exactly the ones where
the difference matters.
"""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, model_validator

from tracesheet.model.base import Model
from tracesheet.model.dates import MonthDay
from tracesheet.model.ids import CompanyId
from tracesheet.model.money import Currency

DEFAULT_SHARE_CLASS = "registered"
"""The class a company has when it declares none: registered shares."""


def _iso_country(value: str) -> str:
    if not re.fullmatch(r"[A-Z]{2}", value):
        msg = f"{value!r} is not an ISO 3166 alpha-2 country code such as 'CH'"
        raise ValueError(msg)
    return value


CountryCode = Annotated[str, AfterValidator(_iso_country)]
"""Two upper-case letters. Country names are for display, never for stored data."""


def _isin(value: str) -> str:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        msg = f"{value!r} is not an ISIN: two letters, nine characters, one check digit"
        raise ValueError(msg)
    # Letters expand to two digits (A=10 ... Z=35); the Luhn check runs over the result.
    digits = "".join(str(int(ch, 36)) for ch in value)
    total = 0
    for index, ch in enumerate(reversed(digits)):
        d = int(ch)
        if index % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    if total % 10 != 0:
        msg = f"{value!r} fails the ISIN check digit"
        raise ValueError(msg)
    return value


Isin = Annotated[str, AfterValidator(_isin)]
"""An ISIN whose format and check digit have been verified."""


class ReportingStandard(StrEnum):
    """The accounting framework a company's annual report is prepared under."""

    IFRS = "ifrs"
    US_GAAP = "us_gaap"
    SWISS_GAAP_FER = "swiss_gaap_fer"


class Listing(Model):
    """Where and under which identifiers a company's shares trade."""

    venue: str
    ticker: str
    isin: Isin


class Company(Model):
    """A listed company: identity, reporting basis and fiscal calendar."""

    id: CompanyId
    name: str
    listing: Listing
    currency: Currency
    """The currency the company reports in."""
    reporting_standard: ReportingStandard
    domicile_country: CountryCode
    fiscal_year_end: MonthDay
    share_classes: tuple[str, ...] = (DEFAULT_SHARE_CLASS,)
    """Every share class the company has listed, including one since merged into another."""
    delisted_at: AwareDatetime | None = None
    """Present so a universe can keep its delisted companies and avoid survivorship bias."""

    @model_validator(mode="after")
    def _share_classes_named_once(self) -> "Company":
        if not self.share_classes:
            msg = "a company has at least one share class"
            raise ValueError(msg)
        if len(set(self.share_classes)) != len(self.share_classes):
            msg = f"share classes are named once each: {self.share_classes}"
            raise ValueError(msg)
        if any(not name.strip() for name in self.share_classes):
            msg = "a share class has a name"
            raise ValueError(msg)
        return self
