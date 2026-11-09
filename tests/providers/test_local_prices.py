"""The local price file: hand-typed closes, the default source of a share price."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tracesheet.model import Company, CompanyId, Currency, Money
from tracesheet.providers import HandLoaded
from tracesheet.providers.market import LocalPrices, LocalPricesError

DATA = Path(__file__).parents[2] / "data"


@pytest.fixture
def company(acme_root: Path) -> Company:
    return HandLoaded(acme_root).company(CompanyId("acme"))


PRICES = """
[[price]]
company = "acme"
date = 2026-03-10
close = "41.00"
currency = "CHF"
source = "first close"

[[price]]
company = "acme"
date = 2026-03-13
close = "42.50"
currency = "CHF"
source = "later close"

[[price]]
company = "acme"
date = 2026-04-01
close = "45.00"
currency = "CHF"
source = "after the cutoff"

[[price]]
company = "other"
date = 2026-03-12
close = "99.00"
currency = "CHF"
source = "another company"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "prices.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_latest_close_on_or_before_the_cutoff(tmp_path: Path, company: Company) -> None:
    prices = LocalPrices(write(tmp_path, PRICES))
    observation = prices.latest_close(company, date(2026, 3, 20))
    assert observation is not None
    assert observation.date == date(2026, 3, 13)
    assert observation.close == Money.parse("42.50", Currency.CHF)
    assert observation.source == "later close"
    assert observation.company_id == company.id
    assert observation.listing == company.listing


def test_a_close_on_the_cutoff_day_counts(tmp_path: Path, company: Company) -> None:
    observation = LocalPrices(write(tmp_path, PRICES)).latest_close(company, date(2026, 4, 1))
    assert observation is not None and observation.date == date(2026, 4, 1)


def test_other_companies_are_ignored(tmp_path: Path, company: Company) -> None:
    # "other" has a close on the 12th, nearer the cutoff than acme's on the 10th.
    observation = LocalPrices(write(tmp_path, PRICES)).latest_close(company, date(2026, 3, 12))
    assert observation is not None and observation.source == "first close"


def test_nothing_before_the_cutoff_is_none(tmp_path: Path, company: Company) -> None:
    assert LocalPrices(write(tmp_path, PRICES)).latest_close(company, date(2026, 1, 1)) is None


def test_a_missing_file_is_no_price(tmp_path: Path, company: Company) -> None:
    assert LocalPrices(tmp_path / "absent.toml").latest_close(company, date(2026, 3, 20)) is None


def test_retrieved_at_is_the_close_date(tmp_path: Path, company: Company) -> None:
    observation = LocalPrices(write(tmp_path, PRICES)).latest_close(company, date(2026, 3, 20))
    assert observation is not None
    assert observation.retrieved_at == datetime(2026, 3, 13, tzinfo=UTC)


def test_a_bare_number_close_is_refused(tmp_path: Path, company: Company) -> None:
    text = 'company = "acme"\ndate = 2026-03-10\nclose = 41.0\ncurrency = "CHF"\nsource = "x"'
    with pytest.raises(LocalPricesError, match="quotes"):
        LocalPrices(write(tmp_path, f"[[price]]\n{text}\n")).latest_close(
            company, date(2026, 3, 20)
        )


def test_an_unknown_field_is_refused(tmp_path: Path, company: Company) -> None:
    text = PRICES + '\n[[price]]\ncompany = "acme"\ndate = 2026-03-11\nclose = "1"\n'
    text += 'currency = "CHF"\nsource = "x"\nvolume = "100"\n'
    with pytest.raises(LocalPricesError, match="volume"):
        LocalPrices(write(tmp_path, text)).latest_close(company, date(2026, 3, 20))


def test_an_unknown_currency_is_refused(tmp_path: Path, company: Company) -> None:
    text = PRICES.replace(
        'currency = "CHF"\nsource = "first close"', 'currency = "XYZ"\nsource = "s"'
    )
    with pytest.raises(LocalPricesError, match="currency"):
        LocalPrices(write(tmp_path, text)).latest_close(company, date(2026, 3, 20))


@pytest.mark.parametrize("close", ["22,10", "CHF 22.10", "", "NaN", "Infinity"])
def test_a_close_that_is_not_a_number_is_refused(
    tmp_path: Path, company: Company, close: str
) -> None:
    text = PRICES.replace('close = "42.50"', f'close = "{close}"')
    with pytest.raises(LocalPricesError, match=r"prices\.toml: price 2 \(acme, 2026-03-13\)"):
        LocalPrices(write(tmp_path, text)).latest_close(company, date(2026, 3, 11))


def test_two_closes_for_one_day_are_refused(tmp_path: Path, company: Company) -> None:
    text = PRICES + '\n[[price]]\ncompany = "acme"\ndate = 2026-03-13\nclose = "43.00"\n'
    text += 'currency = "CHF"\nsource = "a second opinion"\n'
    with pytest.raises(LocalPricesError, match="2026-03-13"):
        LocalPrices(write(tmp_path, text)).latest_close(company, date(2026, 3, 20))


def test_invalid_toml_names_the_file(tmp_path: Path, company: Company) -> None:
    with pytest.raises(LocalPricesError, match=r"prices\.toml"):
        LocalPrices(write(tmp_path, "[[price]\n")).latest_close(company, date(2026, 3, 20))


def test_the_shipped_price_file() -> None:
    kn = HandLoaded(DATA / "companies").company(CompanyId("kuehne-nagel"))
    observation = LocalPrices(DATA / "prices.toml").latest_close(kn, date(2026, 11, 9))
    assert observation is not None
    assert observation.date == date(2026, 10, 22)
    assert observation.close == Money.parse("224.10", Currency.CHF)
    assert observation.source == "SIX Swiss Exchange close, retrieved via EODHD on 2026-10-23"
