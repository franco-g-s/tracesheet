"""The command line: load, evaluate and render, wired to the stages beneath them."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tracesheet.cli import choose_price, main
from tracesheet.model import Company, CompanyId, Money, PriceObservation
from tracesheet.providers import FetchError, HandLoaded
from tracesheet.providers.market import TOKEN_VARIABLE, LocalPrices

AS_OF = date(2026, 3, 31)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the network: start every test without a market token."""
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)


def _price(company: Company, source: str, on: date = AS_OF) -> PriceObservation:
    return PriceObservation(
        company_id=company.id,
        listing=company.listing,
        date=on,
        close=Money.parse("40.00", company.currency),
        source=source,
        retrieved_at=datetime(2026, 3, 31, tzinfo=UTC),
    )


class _Feed:
    def __init__(self, result: PriceObservation | None, *, fail: bool = False) -> None:
        self._result = result
        self._fail = fail

    def latest_close(self, company: Company, on_or_before: date) -> PriceObservation | None:
        del company, on_or_before
        if self._fail:
            raise FetchError("offline")
        return self._result


@pytest.fixture
def company(acme_root: Path) -> Company:
    return HandLoaded(acme_root).company(CompanyId("acme"))


def test_load_ties_out_every_record(acme_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["load", "acme", "--root", str(acme_root)]) == 0
    out = capsys.readouterr().out
    assert out.count("ties out") == 2


def test_load_reports_a_record_that_does_not_tie(
    acme_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "companies"
    (root / "acme").mkdir(parents=True)
    for source in (acme_root / "acme").iterdir():
        text = source.read_text(encoding="utf-8")
        if source.name == "fy2025.toml":
            text = text.replace('value = "905.0"', 'value = "955.0"', 1)
        (root / "acme" / source.name).write_text(text, encoding="utf-8")
    assert main(["load", "acme", "--root", str(root)]) == 1
    assert "fy2025.toml" in capsys.readouterr().out


def test_unknown_company_exits_2_with_a_plain_message(
    acme_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for command in ("load", "evaluate", "render"):
        assert main([command, "nobody", "--root", str(acme_root)]) == 2
    err = capsys.readouterr().err
    assert "nobody" in err
    assert "Traceback" not in err


def test_a_bad_date_is_a_usage_error(acme_root: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["render", "acme", "--root", str(acme_root), "--as-of", "yesterday"])
    assert caught.value.code == 2


def test_render_writes_the_sheet(acme_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "acme.html"
    argv = ["render", "acme", "--root", str(acme_root), "--as-of", "2026-03-31", "--out", str(out)]
    assert main([*argv, "--no-price"]) == 0
    assert "Acme" in out.read_text(encoding="utf-8")


def test_render_stores_nothing_and_evaluate_stores_a_manifest(
    acme_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    store = tmp_path / "evaluations"
    base = ["--root", str(acme_root), "--as-of", "2026-03-31", "--no-price"]
    main(
        [
            "render",
            "acme",
            *base,
            "--out",
            str(tmp_path / "a.html"),
        ]
    )
    assert not Path("data").exists()
    capsys.readouterr()
    assert main(["evaluate", "acme", *base, "--store", str(store)]) == 0
    manifest_id = capsys.readouterr().out.strip()
    assert manifest_id
    assert any(manifest_id in path.name for path in store.rglob("*"))


def test_the_local_file_is_used_without_a_token(
    company: Company, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prices = tmp_path / "prices.toml"
    prices.write_text(
        '[[price]]\ncompany = "acme"\ndate = 2026-03-10\nclose = "41.00"\n'
        'currency = "CHF"\nsource = "typed in"\n',
        encoding="utf-8",
    )
    price = choose_price(company, AS_OF, LocalPrices(prices))
    assert price is not None
    assert price.source == "typed in"
    assert "typed in" in capsys.readouterr().err


def test_the_feed_wins_when_it_answers(
    company: Company, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _price(company, "live")
    local = _Feed(_price(company, "local"))
    assert choose_price(company, AS_OF, local, feed=_Feed(live)) == live
    assert "eodhd" in capsys.readouterr().err


@pytest.mark.parametrize("feed", [_Feed(None), _Feed(None, fail=True)])
def test_a_failing_or_empty_feed_falls_back_to_the_local_file(
    company: Company, feed: _Feed, capsys: pytest.CaptureFixture[str]
) -> None:
    local = _price(company, "local")
    assert choose_price(company, AS_OF, _Feed(local), feed=feed) == local
    assert "falling back" in capsys.readouterr().err


def test_no_source_gives_no_price(company: Company, capsys: pytest.CaptureFixture[str]) -> None:
    assert choose_price(company, AS_OF, _Feed(None)) is None
    assert "no price" in capsys.readouterr().err


def test_the_committed_example_company_renders(tmp_path: Path) -> None:
    repo = Path(__file__).parents[1]
    out = tmp_path / "kn.html"
    argv = [
        "render",
        "kuehne-nagel",
        "--as-of",
        "2026-11-09",
        "--root",
        str(repo / "data" / "companies"),
        "--prices",
        str(repo / "data" / "prices.toml"),
        "--out",
        str(out),
    ]
    assert main(argv) == 0
    assert "Kühne" in out.read_text(encoding="utf-8")
