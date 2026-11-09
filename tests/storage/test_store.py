"""The store: write-once, content-addressed evaluations that verify themselves on load."""

import hashlib
import json
import re
import stat
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tracesheet.evaluate import evaluate
from tracesheet.model import (
    CompanyId,
    Currency,
    Evaluation,
    ExchangeRate,
    Money,
    NotMeaningful,
    PriceObservation,
    Traced,
    Unit,
)
from tracesheet.model.traced import observed
from tracesheet.storage import Store, StoreError

ACME = CompanyId("acme")
AS_OF = datetime(2026, 6, 30, tzinfo=UTC)
CREATED = datetime(2026, 7, 1, 8, 30, 15, 123456, tzinfo=UTC)


@pytest.fixture
def evaluation(acme_root: Path) -> Evaluation:
    return evaluate(acme_root, ACME, AS_OF, None, created_at=CREATED)


@pytest.fixture
def priced(acme_root: Path, evaluation: Evaluation) -> Evaluation:
    price = PriceObservation(
        company_id=ACME,
        listing=evaluation.company.listing,
        date=date(2026, 6, 30),
        close=Money(amount=Decimal("41.20"), currency=Currency.CHF),
        source="test close",
        retrieved_at=datetime(2026, 6, 30, 18, tzinfo=UTC),
    )
    return evaluate(acme_root, ACME, AS_OF, price, created_at=CREATED)


def snapshot(root: Path) -> dict[Path, tuple[bytes, int]]:
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def node_files(root: Path) -> list[Path]:
    return sorted((root / "nodes").glob("*/*.json"))


def rewrite(path: Path, data: dict[str, Any]) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def test_save_then_load_gives_back_an_equal_evaluation(
    tmp_path: Path, evaluation: Evaluation
) -> None:
    store = Store(tmp_path)
    loaded = store.load(store.save(evaluation))
    assert loaded == evaluation
    # Not merely equal: the order the catalogue gave the measures in survives too.
    assert list(loaded.metrics.years[-1].values) == list(evaluation.metrics.years[-1].values)


def test_multiples_round_trip(tmp_path: Path, priced: Evaluation) -> None:
    assert priced.multiples is not None
    store = Store(tmp_path)
    assert store.load(store.save(priced)) == priced


def test_round_trip_keeps_not_meaningful_values(tmp_path: Path, evaluation: Evaluation) -> None:
    reasons = [
        value.reason
        for year in evaluation.metrics.years
        for value in year.values.values()
        if isinstance(value, NotMeaningful)
    ]
    assert reasons, "the fixture should have at least one n/m measure"
    store = Store(tmp_path)
    loaded = store.load(store.save(evaluation))
    assert [
        value.reason
        for year in loaded.metrics.years
        for value in year.values.values()
        if isinstance(value, NotMeaningful)
    ] == reasons


def test_layout_one_file_per_node_and_one_manifest(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)

    assert re.fullmatch(r"20260701T083015123456Z-[0-9a-f]{8}", manifest_id)
    manifest = tmp_path / "evaluations" / "acme" / f"{manifest_id}.json"
    assert manifest.is_file()
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:8]
    assert manifest_id.endswith(digest)

    files = node_files(tmp_path)
    assert files
    for path in files:
        assert path.parent.name == path.stem[:2]
        assert len(path.stem) == 32
    # A figure appears in the manifest only as its id.
    text = manifest.read_text(encoding="utf-8")
    assert '"origin"' not in text
    assert '"transform"' not in text


def test_saving_twice_changes_nothing(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    first = store.save(evaluation)
    before = snapshot(tmp_path)

    assert store.save(evaluation) == first
    assert snapshot(tmp_path) == before


def test_files_are_written_read_only(tmp_path: Path, evaluation: Evaluation) -> None:
    Store(tmp_path).save(evaluation)
    for path in tmp_path.rglob("*.json"):
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def test_a_tampered_filed_figure_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path, data = next(
        (p, d)
        for p in node_files(tmp_path)
        if (d := json.loads(p.read_text(encoding="utf-8"))).get("origin", {}).get("kind") == "filed"
        and "amount" in d["value"]
    )
    data["value"]["amount"] = str(Decimal(data["value"]["amount"]) + 1)
    rewrite(path, data)

    with pytest.raises(StoreError, match="altered"):
        store.load(manifest_id)


def test_a_tampered_derived_figure_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path, data = next(
        (p, d)
        for p in node_files(tmp_path)
        if "transform" in (d := json.loads(p.read_text(encoding="utf-8")))
        and isinstance(d["value"], str)
    )
    data["value"] = str(Decimal(data["value"]) + 1)
    rewrite(path, data)

    with pytest.raises(StoreError, match=path.name):
        store.load(manifest_id)


def test_a_missing_figure_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    node_files(tmp_path)[0].unlink()

    with pytest.raises(StoreError, match="missing"):
        store.load(manifest_id)


def test_a_tampered_manifest_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path = tmp_path / "evaluations" / "acme" / f"{manifest_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["code_version"] = "9.9.9"
    rewrite(path, data)

    with pytest.raises(StoreError, match="does not match"):
        store.load(manifest_id)


def test_an_unknown_schema_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path = tmp_path / "evaluations" / "acme" / f"{manifest_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    content = json.dumps(data).encode()
    stamp = manifest_id.split("-")[0]
    forged = path.with_name(f"{stamp}-{hashlib.sha256(content).hexdigest()[:8]}.json")
    forged.write_bytes(content)

    with pytest.raises(StoreError, match="schema version 2"):
        store.load(forged.stem)


def test_a_manifest_that_does_not_reproduce_its_bytes_is_refused(
    tmp_path: Path, evaluation: Evaluation
) -> None:
    # A hand-written manifest with a valid digest but a non-canonical form, here a number
    # where the store writes a string, is not one the store wrote.
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path = tmp_path / "evaluations" / "acme" / f"{manifest_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["metrics"]["years"][0]["fiscal_year"] = "2024"
    content = json.dumps(data).encode()
    stamp = manifest_id.split("-")[0]
    forged = path.with_name(f"{stamp}-{hashlib.sha256(content).hexdigest()[:8]}.json")
    forged.write_bytes(content)

    with pytest.raises(StoreError, match="re-encode"):
        store.load(forged.stem)


def test_write_once_refuses_different_content_under_a_taken_name(
    tmp_path: Path, evaluation: Evaluation
) -> None:
    store = Store(tmp_path)
    store.save(evaluation)
    path = node_files(tmp_path)[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["unit"] = "nonsense"
    rewrite(path, data)

    with pytest.raises(StoreError, match="is ever overwritten"):
        store.save(evaluation)


def test_unknown_and_malformed_ids(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with pytest.raises(StoreError, match="no evaluation"):
        store.load("20260701T083015123456Z-0123abcd")
    with pytest.raises(StoreError, match="not an evaluation id"):
        store.load("../../etc/passwd")


def test_latest(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    assert store.latest(ACME) is None

    later = evaluation.model_copy(update={"created_at": CREATED + timedelta(days=1)})
    store.save(later)
    store.save(evaluation)

    latest = store.latest(ACME)
    assert latest is not None
    assert latest.created_at == later.created_at
    assert store.latest(CompanyId("nobody")) is None


def test_nodes_are_shared_between_evaluations(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    store.save(evaluation)
    count = len(node_files(tmp_path))
    store.save(evaluation.model_copy(update={"created_at": CREATED + timedelta(hours=1)}))

    assert len(node_files(tmp_path)) == count
    assert len(list((tmp_path / "evaluations" / "acme").iterdir())) == 2


def test_loaded_figures_keep_their_trail(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    loaded = store.load(store.save(evaluation))
    original = evaluation.metrics.years[-1].values["revenue"]
    again = loaded.metrics.years[-1].values["revenue"]
    assert isinstance(original, Traced)
    assert isinstance(again, Traced)
    assert again.id == original.id
    assert again.explain() == original.explain()


def test_a_node_file_of_the_wrong_shape_is_refused(tmp_path: Path, evaluation: Evaluation) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path = next(
        p for p in node_files(tmp_path) if "origin" in json.loads(p.read_text(encoding="utf-8"))
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["origin"] = ["not", "an", "object"]
    rewrite(path, data)

    with pytest.raises(StoreError, match=path.name):
        store.load(manifest_id)


def test_a_converted_price_round_trips_with_its_rate(
    tmp_path: Path, acme_root: Path, evaluation: Evaluation
) -> None:
    price = PriceObservation(
        company_id=ACME,
        listing=evaluation.company.listing,
        date=date(2026, 6, 30),
        close=Money(amount=Decimal("44.00"), currency=Currency.EUR),
        source="test close",
        retrieved_at=datetime(2026, 6, 30, 18, tzinfo=UTC),
    )
    rate = observed(
        ExchangeRate(rate=Decimal("0.9350"), base=Currency.EUR, quote=Currency.CHF),
        Unit.EXCHANGE_RATE,
        what="ECB reference rate CHF/EUR",
        source="ECB reference rate",
        observed_at=datetime(2026, 6, 30, 14, 15, tzinfo=UTC),
    )
    converted = evaluate(acme_root, ACME, AS_OF, price, rate, created_at=CREATED)
    assert converted.multiples is not None
    assert converted.multiples.exchange_rate is not None

    store = Store(tmp_path)
    loaded = store.load(store.save(converted))
    assert loaded == converted
    assert loaded.multiples is not None
    assert loaded.multiples.exchange_rate == rate


def test_a_leftover_partial_file_does_not_block_a_save(
    tmp_path: Path, evaluation: Evaluation
) -> None:
    store = Store(tmp_path)
    manifest_id = store.save(evaluation)
    path = node_files(tmp_path)[0]
    content = path.read_bytes()
    path.unlink()
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(b"half a fi")
    partial.chmod(stat.S_IRUSR)

    assert store.save(evaluation) == manifest_id
    assert path.read_bytes() == content
    assert not partial.exists()
