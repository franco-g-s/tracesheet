"""ECB reference rates: daily, free, no key; the ECB is cited as the source.

The ECB publishes every rate against the euro, so this adapter serves ``EUR`` as the base
only; CHF per USD is ``cross_rate`` over two of its rates.
"""

import csv
import io
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from tracesheet.model import Currency
from tracesheet.provenance import ExchangeRate, Traced, Unit, observed
from tracesheet.providers.fetch import Fetcher, FetchError

BASE = "https://data-api.ecb.europa.eu/service/data/EXR"
PUBLISHED_AT = time(14, 15)
"""The reference rates are fixed at 14:15 CET."""
FRANKFURT = ZoneInfo("Europe/Berlin")


class Ecb:
    """Daily euro reference rates from the ECB Data Portal, each an observed leaf."""

    name = "ecb"

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetch = fetcher

    def rates(self, base: Currency, quote: Currency, since: date) -> tuple[Traced, ...]:
        if base is not Currency.EUR:
            msg = (
                f"the ECB publishes rates against EUR only, not {base}; "
                "fetch both EUR crosses and use cross_rate"
            )
            raise FetchError(msg)
        key = f"D.{quote.value}.EUR.SP00.A"
        url = f"{BASE}/{key}?startPeriod={since.isoformat()}&format=csvdata"
        body = self._fetch(url, {}).decode("utf-8-sig")
        leaves: list[Traced] = []
        for row in csv.DictReader(io.StringIO(body)):
            day = date.fromisoformat(row["TIME_PERIOD"])
            value = row["OBS_VALUE"].strip()
            if not value:
                continue
            leaves.append(
                observed(
                    ExchangeRate(rate=Decimal(value), base=Currency.EUR, quote=quote),
                    Unit.EXCHANGE_RATE,
                    what=f"ECB reference rate {quote.value}/EUR",
                    source=f"ECB Data Portal EXR.{key}",
                    observed_at=datetime.combine(day, PUBLISHED_AT, tzinfo=FRANKFURT),
                )
            )
        leaves.sort(key=lambda leaf: leaf.origin.observed_at)  # type: ignore[union-attr]
        return tuple(leaves)
