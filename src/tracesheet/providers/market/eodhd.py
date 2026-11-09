"""EODHD end-of-day adapter: prices, dividends and splits for SIX-listed shares.

Optional: used only when ``TRACESHEET_EODHD_TOKEN`` is set, and the token is never written
anywhere. EODHD's terms allow private, non-commercial use on one account and no
redistribution, which is why fetched prices stay in the gitignored cache. JSON is parsed
with every number as a ``Decimal``: a vendor float never becomes a Python float. Every
figure is a claim about a day, sourced and dated.
"""

import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode

from tracesheet.model import (
    ActionKind,
    Company,
    CorporateAction,
    Money,
    PriceObservation,
    SharesObservation,
)
from tracesheet.providers.fetch import Fetcher, FetchError

BASE = "https://eodhd.com/api"
TOKEN_VARIABLE = "TRACESHEET_EODHD_TOKEN"
_SUFFIX = {"SIX": "SW"}
"""EODHD's exchange code per listing venue. Add a venue when the universe widens."""
LOOKBACK = timedelta(days=14)
"""How far back ``latest_close`` asks for closes: long enough to span a holiday week."""


class Eodhd:
    """End-of-day prices and corporate actions from EODHD, fetched through a ``Fetcher``."""

    name = "eodhd"

    def __init__(self, fetcher: Fetcher, token: str | None = None) -> None:
        self._fetch = fetcher
        self._token = token or os.environ.get(TOKEN_VARIABLE)
        if not self._token:
            msg = f"no EODHD token: set {TOKEN_VARIABLE}"
            raise FetchError(msg)

    def prices(self, company: Company, since: date) -> tuple[PriceObservation, ...]:
        symbol = self.symbol(company)
        rows = self._get(f"eod/{symbol}", {"from": since.isoformat(), "period": "d"})
        fetched = datetime.now(tz=UTC)
        observations = [
            PriceObservation(
                company_id=company.id,
                listing=company.listing,
                date=date.fromisoformat(str(row["date"])),
                close=Money(amount=_decimal(row["close"]), currency=company.currency),
                open=_money(row.get("open"), company),
                high=_money(row.get("high"), company),
                low=_money(row.get("low"), company),
                volume=_optional_decimal(row.get("volume")),
                vendor_adjusted_close=_money(row.get("adjusted_close"), company),
                source=f"{self.name}:{symbol}",
                retrieved_at=fetched,
            )
            for row in rows
        ]
        observations.sort(key=lambda o: o.date)
        return tuple(observations)

    def latest_close(self, company: Company, on_or_before: date) -> PriceObservation | None:
        """The most recent close on or before ``on_or_before`` within ``LOOKBACK``. The
        cutoff is applied here rather than by the vendor, so a later day it serves anyway
        is never used."""
        rows = self.prices(company, on_or_before - LOOKBACK)
        eligible = [row for row in rows if row.date <= on_or_before]
        return eligible[-1] if eligible else None

    def shares(self, company: Company) -> tuple[SharesObservation, ...]:
        """Share counts sit behind EODHD's fundamentals plan; the count in the annual
        report is the source instead. Empty on purpose."""
        del company
        return ()

    def corporate_actions(self, company: Company, since: date) -> tuple[CorporateAction, ...]:
        symbol = self.symbol(company)
        fetched = datetime.now(tz=UTC)
        actions: list[CorporateAction] = []
        for row in self._get(f"div/{symbol}", {"from": since.isoformat()}):
            actions.append(
                CorporateAction(
                    company_id=company.id,
                    kind=ActionKind.DIVIDEND,
                    ex_date=date.fromisoformat(str(row["date"])),
                    record_date=_date(row.get("recordDate")),
                    pay_date=_date(row.get("paymentDate")),
                    amount=Money(
                        amount=_decimal(row["value"]),
                        currency=type(company.currency)(
                            str(row.get("currency", company.currency.value)).upper()
                        ),
                    ),
                    source=f"{self.name}:{symbol}",
                    retrieved_at=fetched,
                )
            )
        for row in self._get(f"splits/{symbol}", {"from": since.isoformat()}):
            new, old = str(row["split"]).split("/")
            ratio = Fraction(Decimal(new)) / Fraction(Decimal(old))
            actions.append(
                CorporateAction(
                    company_id=company.id,
                    kind=ActionKind.SPLIT if ratio > 1 else ActionKind.REVERSE_SPLIT,
                    ex_date=date.fromisoformat(str(row["date"])),
                    new_shares=ratio.numerator,
                    old_shares=ratio.denominator,
                    source=f"{self.name}:{symbol}",
                    retrieved_at=fetched,
                )
            )
        actions.sort(key=lambda a: a.ex_date)
        return tuple(actions)

    @staticmethod
    def symbol(company: Company) -> str:
        suffix = _SUFFIX.get(company.listing.venue)
        if suffix is None:
            msg = f"{company.id}: no EODHD exchange code for venue {company.listing.venue!r}"
            raise FetchError(msg)
        return f"{company.listing.ticker}.{suffix}"

    def _get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        assert self._token is not None
        query = urlencode({**params, "fmt": "json", "api_token": self._token})
        body = self._fetch(f"{BASE}/{path}?{query}", {})
        try:
            data = json.loads(body, parse_float=Decimal, parse_int=Decimal)
        except json.JSONDecodeError as error:
            msg = f"{path}: not JSON ({error})"
            raise FetchError(msg) from error
        if not isinstance(data, list):
            msg = f"{path}: expected a list, got {type(data).__name__}"
            raise FetchError(msg)
        return [row for row in data if isinstance(row, dict)]


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _money(value: object, company: Company) -> Money | None:
    return None if value is None else Money(amount=_decimal(value), currency=company.currency)


def _date(value: object) -> date | None:
    return None if value in (None, "") else date.fromisoformat(str(value))
