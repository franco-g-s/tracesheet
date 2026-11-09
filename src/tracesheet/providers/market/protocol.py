"""The market-data interfaces: a vendor feed, a source of one closing price, and exchange
rates."""

from datetime import date
from typing import Protocol, runtime_checkable

from tracesheet.model import Company, CorporateAction, Currency, PriceObservation, SharesObservation
from tracesheet.provenance import Traced


@runtime_checkable
class ClosingPrices(Protocol):
    """Anything that can name a company's latest close on or before a day."""

    def latest_close(self, company: Company, on_or_before: date) -> PriceObservation | None:
        """The most recent close on or before ``on_or_before``, or ``None`` if there is none."""
        ...


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def prices(self, company: Company, since: date) -> tuple[PriceObservation, ...]:
        """Daily closes from ``since``, unadjusted, oldest first."""
        ...

    def shares(self, company: Company) -> tuple[SharesObservation, ...]:
        """Share counts the vendor serves, each with its kind; may be empty."""
        ...

    def corporate_actions(self, company: Company, since: date) -> tuple[CorporateAction, ...]:
        """Dividends and splits from ``since``, as the vendor reports them: claims, until
        the issuer's own notice confirms the kind."""
        ...


@runtime_checkable
class RatesProvider(Protocol):
    name: str

    def rates(self, base: Currency, quote: Currency, since: date) -> tuple[Traced, ...]:
        """Observed exchange-rate leaves, one per day, oldest first."""
        ...
