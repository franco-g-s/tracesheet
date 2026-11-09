"""The runner: typed-in files in, one complete evaluation out."""

import re
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import tracesheet
from tracesheet import evaluate as runner
from tracesheet.evaluate import code_version, evaluate
from tracesheet.model import (
    SCHEMA_VERSION,
    CompanyId,
    Currency,
    Listing,
    Money,
    PriceObservation,
    RecordId,
)

ACME = CompanyId("acme")
AS_OF = datetime(2026, 6, 30, tzinfo=UTC)
CREATED = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)


def acme_price(listing: Listing) -> PriceObservation:
    return PriceObservation(
        company_id=ACME,
        listing=listing,
        date=date(2026, 6, 30),
        close=Money(amount=Decimal("41.20"), currency=Currency.CHF),
        source="test close",
        retrieved_at=datetime(2026, 6, 30, 18, tzinfo=UTC),
    )


def test_acme_has_metrics_for_both_years_and_ties_out(acme_root: Path) -> None:
    evaluation = evaluate(acme_root, ACME, AS_OF, None, created_at=CREATED)

    assert evaluation.schema_version == SCHEMA_VERSION == 1
    assert evaluation.company.id == ACME
    assert evaluation.as_of == AS_OF
    assert evaluation.created_at == CREATED
    assert [y.fiscal_year for y in evaluation.metrics.years] == [2024, 2025]
    assert evaluation.normalized.fiscal_years == (2024, 2025)
    assert dict(evaluation.tie_out) == {RecordId("fy2024"): (), RecordId("fy2025"): ()}
    assert evaluation.multiples is None


def test_only_what_was_filed_by_as_of_is_tied_out(acme_root: Path) -> None:
    # Fiscal 2025 was filed on 9 March 2026; a day before, only fiscal 2024 exists.
    evaluation = evaluate(acme_root, ACME, datetime(2026, 3, 8, tzinfo=UTC), None)

    assert evaluation.normalized.fiscal_years == (2024,)
    assert dict(evaluation.tie_out) == {RecordId("fy2024"): ()}


def test_a_price_gives_multiples(acme_root: Path) -> None:
    listing = evaluate(acme_root, ACME, AS_OF, None).company.listing
    evaluation = evaluate(acme_root, ACME, AS_OF, acme_price(listing))

    assert evaluation.multiples is not None
    assert evaluation.multiples.fiscal_year == 2025
    assert evaluation.multiples.price_date == date(2026, 6, 30)


def test_created_at_defaults_to_now_in_utc(acme_root: Path) -> None:
    before = datetime.now(UTC)
    evaluation = evaluate(acme_root, ACME, AS_OF, None)
    after = datetime.now(UTC)

    assert before <= evaluation.created_at <= after
    assert evaluation.created_at.utcoffset() == UTC.utcoffset(None)


def test_code_version_is_the_package_version_and_maybe_a_commit() -> None:
    version = re.escape(tracesheet.__version__)
    assert re.fullmatch(rf"{version}(\+[0-9a-f]{{4,40}})?", code_version())


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("git"),
        PermissionError("git"),
        subprocess.CalledProcessError(128, ["git"]),
        subprocess.TimeoutExpired(["git"], 5),
    ],
)
def test_code_version_never_fails(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    def broken(*_args: object, **_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(subprocess, "run", broken)
    assert code_version() == tracesheet.__version__


def test_code_version_ignores_a_repository_that_is_not_this_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Installed into a virtual environment inside someone else's repository, git answers
    # for that repository; its commit says nothing about this code.
    def elsewhere(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git"], 0, stdout=f"abc1234\n{tmp_path}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", elsewhere)
    assert code_version() == tracesheet.__version__


def test_code_version_names_the_commit_of_its_own_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    top_level = runner._PACKAGE.parent.parent

    def checkout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git"], 0, stdout=f"{top_level}\nabc1234\n", stderr="")

    monkeypatch.setattr(subprocess, "run", checkout)
    assert code_version() == f"{tracesheet.__version__}+abc1234"
