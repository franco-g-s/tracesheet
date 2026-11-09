"""The market adapters: EODHD end-of-day prices, ECB reference rates and the local cache.

Every adapter takes a ``Fetcher``; these tests hand it a fake one, so nothing touches the
network.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tracesheet.model import (
    ActionKind,
    Company,
    CompanyId,
    Currency,
    ExchangeRate,
    Listing,
    Money,
    PriceObservation,
)
from tracesheet.providers import FetchError, HandLoaded, redact, urllib_fetch
from tracesheet.providers.market import (
    TOKEN_VARIABLE,
    CacheError,
    ClosingPrices,
    Ecb,
    Eodhd,
    LocalPrices,
    MarketCache,
    MarketDataProvider,
    RatesProvider,
)


@pytest.fixture
def company(acme_root: Path) -> Company:
    return HandLoaded(acme_root).company(CompanyId("acme"))


class FakeFetcher:
    """Serves a canned body per URL path and records every URL asked for."""

    def __init__(self, bodies: Mapping[str, object]) -> None:
        self.bodies = bodies
        self.urls: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> bytes:
        self.urls.append(url)
        for fragment, body in self.bodies.items():
            if fragment in url:
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise FetchError(f"unexpected URL {url}")


EOD = [
    {"date": "2026-03-12", "open": 41.1, "high": 42.0, "low": 40.9, "close": 41.55,
     "adjusted_close": 40.0, "volume": 1200},
    {"date": "2026-03-13", "close": 42.15},
    {"date": "2026-03-16", "close": 43.0},
]  # fmt: skip


def test_token_variable_name() -> None:
    assert TOKEN_VARIABLE == "TRACESHEET_EODHD_TOKEN"


def test_no_token_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)
    with pytest.raises(FetchError, match=TOKEN_VARIABLE):
        Eodhd(FakeFetcher({}))


def test_token_from_the_environment(monkeypatch: pytest.MonkeyPatch, company: Company) -> None:
    monkeypatch.setenv(TOKEN_VARIABLE, "from-env")
    fetcher = FakeFetcher({"/eod/": EOD})
    Eodhd(fetcher).prices(company, date(2026, 3, 1))
    assert "api_token=from-env" in fetcher.urls[0]


def test_prices_are_decimals_oldest_first(company: Company) -> None:
    fetcher = FakeFetcher({"/eod/": list(reversed(EOD))})
    rows = Eodhd(fetcher, token="t").prices(company, date(2026, 3, 1))
    assert [r.date for r in rows] == [date(2026, 3, 12), date(2026, 3, 13), date(2026, 3, 16)]
    first = next(r for r in rows if r.date == date(2026, 3, 12))
    assert first.close == Money(amount=Decimal("41.55"), currency=company.currency)
    assert first.vendor_adjusted_close == Money(amount=Decimal("40.0"), currency=company.currency)
    assert first.volume == Decimal(1200)
    assert first.source == "eodhd:ACME.SW"
    assert "eod/ACME.SW" in fetcher.urls[0] and "from=2026-03-01" in fetcher.urls[0]


def test_latest_close_keeps_only_days_on_or_before(company: Company) -> None:
    fetcher = FakeFetcher({"/eod/": EOD})
    observation = Eodhd(fetcher, token="t").latest_close(company, date(2026, 3, 15))
    assert observation is not None and observation.date == date(2026, 3, 13)


def test_latest_close_with_nothing_served_is_none(company: Company) -> None:
    fetcher = FakeFetcher({"/eod/": []})
    assert Eodhd(fetcher, token="t").latest_close(company, date(2026, 3, 15)) is None


def test_an_unknown_venue_is_refused(company: Company) -> None:
    elsewhere = company.model_copy(
        update={"listing": Listing(venue="XETRA", ticker="ACM", isin=company.listing.isin)}
    )
    with pytest.raises(FetchError, match="XETRA"):
        Eodhd(FakeFetcher({}), token="t").prices(elsewhere, date(2026, 3, 1))


def test_a_body_that_is_not_a_list_is_refused(company: Company) -> None:
    fetcher = FakeFetcher({"/eod/": {"error": "nope"}})
    with pytest.raises(FetchError, match="expected a list"):
        Eodhd(fetcher, token="t").prices(company, date(2026, 3, 1))


def test_corporate_actions_are_dividends_and_splits(company: Company) -> None:
    fetcher = FakeFetcher(
        {
            "/div/": [{"date": "2025-05-06", "value": 1.5, "currency": "chf"}],
            "/splits/": [{"date": "2025-06-02", "split": "2.000000/1.000000"}],
        }
    )
    actions = Eodhd(fetcher, token="t").corporate_actions(company, date(2025, 1, 1))
    assert [a.kind for a in actions] == [ActionKind.DIVIDEND, ActionKind.SPLIT]
    assert actions[0].amount == Money(amount=Decimal("1.5"), currency=Currency.CHF)
    assert (actions[1].new_shares, actions[1].old_shares) == (2, 1)


def test_ecb_serves_observed_euro_rates() -> None:
    body = b"\xef\xbb\xbfKEY,TIME_PERIOD,OBS_VALUE\nx,2026-03-12,0.9412\nx,2026-03-13,\n"
    rates = Ecb(FakeFetcher({"EXR/D.CHF.EUR": body})).rates(
        Currency.EUR, Currency.CHF, date(2026, 3, 1)
    )
    assert len(rates) == 1
    assert rates[0].value == ExchangeRate(
        rate=Decimal("0.9412"), base=Currency.EUR, quote=Currency.CHF
    )


def test_ecb_refuses_a_non_euro_base() -> None:
    with pytest.raises(FetchError, match="EUR"):
        Ecb(FakeFetcher({})).rates(Currency.USD, Currency.CHF, date(2026, 3, 1))


def test_adapters_meet_their_protocols(company: Company, tmp_path: Path) -> None:
    eodhd = Eodhd(FakeFetcher({}), token="t")
    assert isinstance(eodhd, MarketDataProvider)
    assert isinstance(eodhd, ClosingPrices)
    assert isinstance(LocalPrices(tmp_path / "prices.toml"), ClosingPrices)
    assert isinstance(Ecb(FakeFetcher({})), RatesProvider)


def observation(close: str, day: int = 13) -> PriceObservation:
    return PriceObservation(
        company_id=CompanyId("acme"),
        listing=Listing(venue="SIX", ticker="ACME", isin="CH0025238863"),
        date=date(2026, 3, day),
        close=Money.parse(close, Currency.CHF),
        source="eodhd:ACME.SW",
        retrieved_at=datetime.now(tz=UTC),
    )


def test_cache_appends_new_days_only(tmp_path: Path) -> None:
    cache = MarketCache(tmp_path)
    assert cache.append_prices([observation("42.15"), observation("41.55", day=12)]) == 2
    assert cache.append_prices([observation("42.15")]) == 0
    assert [p.date.day for p in cache.prices(CompanyId("acme"))] == [12, 13]


def test_cache_refuses_a_changed_close(tmp_path: Path) -> None:
    cache = MarketCache(tmp_path)
    cache.append_prices([observation("42.15")])
    with pytest.raises(CacheError, match="2026-03-13"):
        cache.append_prices([observation("99.00")])


# --- The token never reaches an error message ---


def test_a_failed_fetch_does_not_leak_the_token(company: Company) -> None:
    def failing(url: str, headers: Mapping[str, str]) -> bytes:
        raise FetchError(f"{url}: HTTP Error 401: Unauthorized")

    with pytest.raises(FetchError) as caught:
        Eodhd(failing, token="s3cret-token").prices(company, date(2026, 3, 1))
    assert "s3cret-token" not in str(caught.value)
    assert "api_token=***" in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_a_token_echoed_outside_the_query_is_still_redacted(company: Company) -> None:
    def echoing(url: str, headers: Mapping[str, str]) -> bytes:
        raise FetchError("server said: bad key s3cret-token")

    with pytest.raises(FetchError) as caught:
        Eodhd(echoing, token="s3cret-token").prices(company, date(2026, 3, 1))
    assert "s3cret-token" not in str(caught.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://x.test/a?api_token=abc&fmt=json", "https://x.test/a?api_token=***&fmt=json"),
        ("https://x.test/a?fmt=json&token=abc", "https://x.test/a?fmt=json&token=***"),
        ("https://x.test/a?KEY=abc#frag", "https://x.test/a?KEY=***#frag"),
        ("https://x.test/a?api_key=abc: boom", "https://x.test/a?api_key=*** boom"),
        ("https://x.test/a?monkey=abc", "https://x.test/a?monkey=abc"),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_urllib_fetch_redacts_a_refused_url() -> None:
    with pytest.raises(FetchError) as caught:
        urllib_fetch("http://x.test/a?api_token=s3cret-token", {})
    assert "s3cret-token" not in str(caught.value)
