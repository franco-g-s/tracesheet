"""Hand-typed closing prices, read from a TOML file: the default source of a share price.

One ``[[price]]`` table per close::

    [[price]]
    company = "kuehne-nagel"
    date = 2026-10-22
    close = "224.10"
    currency = "CHF"
    source = "SIX Swiss Exchange close, retrieved via EODHD on 2026-10-23"

The close is written in quotes, as text, so it is read as an exact decimal and never as a
float. ``source`` says where the number was read; it travels with the price into every
figure derived from it.
"""

import tomllib
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from tracesheet.model import Company, Currency, Money, PriceObservation


class LocalPricesError(ValueError):
    """The price file cannot be read, or one of its entries is malformed."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"{path}: {detail}")


def _quoted(value: object) -> object:
    if not isinstance(value, str):
        msg = "must be written in quotes, as text; a bare number would be read as a float"
        raise ValueError(msg)
    return value


class _Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    company: str
    date: date
    close: Annotated[str, BeforeValidator(_quoted)]
    currency: Currency
    source: str


class _File(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price: list[_Entry] = []


class LocalPrices:
    """Closing prices from one TOML file. A missing file means no price, not an error."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def latest_close(self, company: Company, on_or_before: date) -> PriceObservation | None:
        """The company's most recent close on or before ``on_or_before``.

        A typed-in close has no fetch time, so ``retrieved_at`` is midnight UTC on the close
        date: the same entry gives the same observation on every run.
        """
        entries = [e for e in self._entries() if e.company == company.id and e.date <= on_or_before]
        if not entries:
            return None
        latest = max(entries, key=lambda e: e.date)
        return PriceObservation(
            company_id=company.id,
            listing=company.listing,
            date=latest.date,
            close=Money.parse(latest.close, latest.currency),
            source=latest.source,
            retrieved_at=datetime.combine(latest.date, time(), tzinfo=UTC),
        )

    def _entries(self) -> list[_Entry]:
        if not self.path.is_file():
            return []
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except OSError as error:
            raise LocalPricesError(self.path, f"cannot be read: {error.strerror}") from error
        except tomllib.TOMLDecodeError as error:
            raise LocalPricesError(self.path, f"is not valid TOML: {error}") from error
        try:
            entries = _File.model_validate(data).price
        except ValidationError as error:
            raise LocalPricesError(self.path, _describe(error)) from error
        seen: set[tuple[str, date]] = set()
        for index, entry in enumerate(entries, start=1):
            _check_close(self.path, index, entry)
            key = (entry.company, entry.date)
            if key in seen:
                detail = f"two closes for {entry.company} on {entry.date.isoformat()}"
                raise LocalPricesError(self.path, detail)
            seen.add(key)
        return entries


def _check_close(path: Path, index: int, entry: _Entry) -> None:
    """Refuse a close that is not a finite decimal number, naming the entry."""
    try:
        amount = Decimal(entry.close)
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite():
        detail = (
            f"price {index} ({entry.company}, {entry.date.isoformat()}): close "
            f'{entry.close!r} is not a number; write it like "224.10"'
        )
        raise LocalPricesError(path, detail)


def _describe(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}"
