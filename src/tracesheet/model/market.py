"""Market observations: a price on a day, shares on a day, and corporate actions.

Every object is dated and sourced, so any figure derived from one can name where it came from.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, model_validator

from tracesheet.model.base import Model
from tracesheet.model.company import Listing
from tracesheet.model.financial_record import Sha256
from tracesheet.model.ids import CompanyId
from tracesheet.model.money import Money, ShareCount


class PriceObservation(Model):
    """One closing price, unadjusted, as the exchange printed it."""

    company_id: CompanyId
    listing: Listing
    date: date
    close: Money
    open: Money | None = None
    high: Money | None = None
    low: Money | None = None
    volume: Decimal | None = None
    vendor_adjusted_close: Money | None = None
    """The vendor's back-adjusted close: a cross-check on our own adjustment, never an input."""
    source: str
    retrieved_at: AwareDatetime

    @model_validator(mode="after")
    def _one_currency(self) -> "PriceObservation":
        for name in ("open", "high", "low", "vendor_adjusted_close"):
            other: Money | None = getattr(self, name)
            if other is not None and other.currency is not self.close.currency:
                msg = f"{name} is in {other.currency}, the close in {self.close.currency}"
                raise ValueError(msg)
        return self


class SharesKind(StrEnum):
    """Vendors do not agree on which count they serve; the field forces the question."""

    ISSUED = "issued"
    OUTSTANDING = "outstanding"
    DILUTED = "diluted"
    FREE_FLOAT = "free_float"


class SharesObservation(Model):
    """Shares on a date, from a source that is not a filing. The report's own count stays a
    line item on the filed record."""

    company_id: CompanyId
    date: date
    count: ShareCount
    kind: SharesKind
    source: str
    retrieved_at: AwareDatetime


class ActionKind(StrEnum):
    DIVIDEND = "dividend"
    CAPITAL_REPAYMENT = "capital_repayment"
    """A payout from capital contribution reserves rather than from profit."""
    SPECIAL_DIVIDEND = "special_dividend"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    BONUS_ISSUE = "bonus_issue"
    """Free shares to existing holders (a capitalisation issue): a split by another name."""
    RIGHTS_ISSUE = "rights_issue"
    CLASS_UNIFICATION = "class_unification"
    """One share class converted into another, which survives."""
    SPIN_OFF = "spin_off"
    DELISTING = "delisting"
    ISIN_CHANGE = "isin_change"
    TICKER_CHANGE = "ticker_change"


_DISTRIBUTIONS = frozenset(
    {ActionKind.DIVIDEND, ActionKind.CAPITAL_REPAYMENT, ActionKind.SPECIAL_DIVIDEND}
)
RATIO_ACTIONS = frozenset(
    {
        ActionKind.SPLIT,
        ActionKind.REVERSE_SPLIT,
        ActionKind.BONUS_ISSUE,
        ActionKind.CLASS_UNIFICATION,
    }
)
"""Actions whose factor is new shares over old shares, two whole numbers."""
SHARE_BASIS_ACTIONS = frozenset({*RATIO_ACTIONS, ActionKind.RIGHTS_ISSUE, ActionKind.SPIN_OFF})
"""Actions that change what one share is. A spin-off is among them so that it is recorded;
no per-share adjustment is derived from it."""


class ActionDocument(Model):
    """The issuer's document an action was read from: which file, which page."""

    document: str
    sha256: Sha256
    page: int | None = None
    """As printed on the page."""
    pdf_page: int | None = None


class RightsTerms(Model):
    """A rights issue's terms: ``offered_shares`` new shares for every ``held_shares``
    held, at ``subscription_price`` each. With the last cum-rights close they give the
    adjustment factor of IAS 33 appendix A2."""

    offered_shares: int
    held_shares: int
    subscription_price: Money

    @model_validator(mode="after")
    def _positive(self) -> "RightsTerms":
        if self.offered_shares <= 0 or self.held_shares <= 0:
            msg = "rights terms are two positive whole numbers of shares"
            raise ValueError(msg)
        if self.subscription_price.amount <= 0:
            msg = "a subscription price is positive"
            raise ValueError(msg)
        return self


class CorporateAction(Model):
    """A dated event that changes what one share is, or pays out per share. The kind of a
    distribution is set from the issuer's own notice, never from a vendor.

    ``confirmed_by`` names what checked the action against the issuer's document; an action
    without it is recorded but not yet verified."""

    company_id: CompanyId
    kind: ActionKind
    ex_date: date
    """For a share-basis action, the first day the shares count on the new basis."""
    record_date: date | None = None
    pay_date: date | None = None
    amount: Money | None = None
    """Per share, for a distribution."""
    new_shares: int | None = None
    """With ``old_shares``: ``old_shares`` shares before are ``new_shares`` after. A 1:5
    split is 5 and 1; a 2-for-3 consolidation 2 and 3; a bonus of 1 free share per 10 held
    11 and 10."""
    old_shares: int | None = None
    printed_factor: Decimal | None = None
    """A rights issue's adjustment factor as the company prints it for its EPS."""
    rights: RightsTerms | None = None
    share_class: str | None = None
    """The class the action applies to. Absent: the company's single class."""
    into_class: str | None = None
    """For a class unification: the class that survives."""
    source: str
    document: ActionDocument | None = None
    quote: str | None = None
    """The sentence of the document that states the action."""
    retrieved_at: AwareDatetime | None = None
    """When a vendor served it. Absent for an action typed from a document."""
    confirmed_by: str | None = None
    """What confirmed it against the issuer: for a distribution, the filed record whose
    declared dividend per share agrees; for a share-basis action, the actions file it was
    typed into."""
    note: str | None = None

    @property
    def effective(self) -> date:
        return self.ex_date

    @property
    def ratio(self) -> Decimal | None:
        """New shares per old share, when the action has two whole numbers."""
        if self.new_shares is None or self.old_shares is None:
            return None
        return Decimal(self.new_shares) / Decimal(self.old_shares)

    @property
    def confirmed(self) -> bool:
        return self.confirmed_by is not None

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> "CorporateAction":
        has_shares = self.new_shares is not None or self.old_shares is not None
        if self.kind in _DISTRIBUTIONS and (self.amount is None or has_shares):
            msg = f"a {self.kind} carries an amount per share and no ratio"
            raise ValueError(msg)
        if self.kind in SHARE_BASIS_ACTIONS and self.amount is not None:
            msg = f"a {self.kind} carries no amount per share"
            raise ValueError(msg)
        if has_shares:
            self._check_ratio()
        elif self.kind in RATIO_ACTIONS:
            msg = f"a {self.kind} carries a ratio: new_shares and old_shares"
            raise ValueError(msg)
        if self.kind is ActionKind.CLASS_UNIFICATION and self.into_class is None:
            msg = "a class unification names the class that survives: into_class"
            raise ValueError(msg)
        if self.kind is not ActionKind.CLASS_UNIFICATION and self.into_class is not None:
            msg = "only a class unification has an into_class"
            raise ValueError(msg)
        if (self.printed_factor is not None or self.rights is not None) and (
            self.kind is not ActionKind.RIGHTS_ISSUE
        ):
            msg = "only a rights issue carries a printed factor or rights terms"
            raise ValueError(msg)
        if self.printed_factor is not None and self.printed_factor <= 0:
            msg = "a printed factor is positive"
            raise ValueError(msg)
        if (
            self.kind is ActionKind.RIGHTS_ISSUE
            and self.confirmed
            and self.printed_factor is None
            and self.rights is None
        ):
            msg = "a confirmed rights issue needs its printed factor or its terms"
            raise ValueError(msg)
        return self

    def _check_ratio(self) -> None:
        if self.kind not in RATIO_ACTIONS:
            msg = f"a {self.kind} carries no new_shares or old_shares"
            raise ValueError(msg)
        if self.new_shares is None or self.old_shares is None:
            msg = "a ratio needs both new_shares and old_shares"
            raise ValueError(msg)
        if self.new_shares <= 0 or self.old_shares <= 0:
            msg = "a split ratio is positive: two positive whole numbers"
            raise ValueError(msg)
        if self.kind in (ActionKind.SPLIT, ActionKind.BONUS_ISSUE) and (
            self.new_shares <= self.old_shares
        ):
            msg = f"a {self.kind} makes more shares: new_shares is above old_shares"
            raise ValueError(msg)
        if self.kind is ActionKind.REVERSE_SPLIT and self.new_shares >= self.old_shares:
            msg = "a reverse split makes fewer shares: new_shares is below old_shares"
            raise ValueError(msg)
