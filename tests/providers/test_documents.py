import hashlib
import shutil
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pytest

from tracesheet.model import CompanyId
from tracesheet.providers.documents import (
    Document,
    DocumentKind,
    DocumentRegistry,
    DocumentsError,
)
from tracesheet.providers.fetch import USER_AGENT, Fetcher, FetchError, urllib_fetch

ACME = CompanyId("acme")
REPORT_2025 = b"Acme Annual Report 2025 (fictional)\n"


class FakeFetcher:
    """Stands in for the network: returns fixed bytes and remembers what was asked."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> bytes:
        self.calls.append(url)
        return self.content


def _report_2025(registry: DocumentRegistry) -> Document:
    document = registry.document(
        ACME, period_end=date(2025, 12, 31), kind=DocumentKind.ANNUAL_REPORT
    )
    assert document is not None
    return document


def test_registry_lists_the_fixture_documents(acme_root: Path) -> None:
    documents = DocumentRegistry(acme_root).documents(ACME)
    assert [d.period.end.year for d in documents] == [2024, 2025]
    assert all(d.kind is DocumentKind.ANNUAL_REPORT for d in documents)
    assert all(d.sha256 is not None for d in documents)


def test_lookup_of_an_absent_document_is_none(acme_root: Path) -> None:
    registry = DocumentRegistry(acme_root)
    assert (
        registry.document(ACME, period_end=date(2023, 12, 31), kind=DocumentKind.ANNUAL_REPORT)
        is None
    )


def test_fetch_stores_the_file_under_its_hash(acme_root: Path, tmp_path: Path) -> None:
    registry = DocumentRegistry(acme_root)
    fetcher = FakeFetcher(REPORT_2025)
    path = registry.fetch(ACME, _report_2025(registry), fetcher, raw_root=tmp_path)
    assert path == tmp_path / "acme" / f"{hashlib.sha256(REPORT_2025).hexdigest()}.pdf"
    assert path.read_bytes() == REPORT_2025
    assert fetcher.calls == ["https://example.com/acme/annual-report-2025.pdf"]


def test_fetch_of_a_stored_file_does_not_download(acme_root: Path, tmp_path: Path) -> None:
    registry = DocumentRegistry(acme_root)
    document = _report_2025(registry)
    registry.fetch(ACME, document, FakeFetcher(REPORT_2025), raw_root=tmp_path)
    again = FakeFetcher(REPORT_2025)
    registry.fetch(ACME, document, again, raw_root=tmp_path)
    assert again.calls == []


def test_fetch_refuses_bytes_that_do_not_match_the_hash(acme_root: Path, tmp_path: Path) -> None:
    registry = DocumentRegistry(acme_root)
    with pytest.raises(FetchError, match="does not match"):
        registry.fetch(ACME, _report_2025(registry), FakeFetcher(b"other"), raw_root=tmp_path)


def test_first_fetch_records_the_hash(acme_root: Path, tmp_path: Path) -> None:
    root = tmp_path / "companies"
    shutil.copytree(acme_root, root)
    path = root / "acme" / "documents.toml"
    text = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(REPORT_2025).hexdigest()
    path.write_text(text.replace(f'sha256 = "{sha}"\n', ""), encoding="utf-8")
    registry = DocumentRegistry(root)
    assert _report_2025(registry).sha256 is None

    registry.fetch(ACME, _report_2025(registry), FakeFetcher(REPORT_2025), raw_root=tmp_path)

    recorded = _report_2025(registry)
    assert recorded.sha256 == sha
    assert recorded.fetched_at is not None
    assert len(tomllib.loads(path.read_text(encoding="utf-8"))["documents"]) == 2


def test_path_of_an_unfetched_document_is_refused(acme_root: Path, tmp_path: Path) -> None:
    registry = DocumentRegistry(acme_root)
    unfetched = _report_2025(registry).model_copy(update={"sha256": None})
    with pytest.raises(FetchError, match="not been fetched"):
        registry.path_for(ACME, unfetched, tmp_path)


def test_unknown_key_in_documents_file_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = tmp_path / "companies"
    shutil.copytree(acme_root, root)
    path = root / "acme" / "documents.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('language = "en"', "skip_pages = [3]", 1),
        encoding="utf-8",
    )
    with pytest.raises(DocumentsError, match="skip_pages"):
        DocumentRegistry(root).documents(ACME)


def test_urllib_fetch_refuses_plain_http() -> None:
    with pytest.raises(FetchError, match="https"):
        urllib_fetch("http://example.com/report.pdf", {})


def test_user_agent_names_the_project() -> None:
    assert USER_AGENT == "Tracesheet/0.1 (+https://github.com/franco-g-s/tracesheet)"


def test_fake_fetcher_satisfies_the_fetcher_type() -> None:
    fetcher: Fetcher = FakeFetcher(b"")
    assert fetcher("https://example.com", {}) == b""
