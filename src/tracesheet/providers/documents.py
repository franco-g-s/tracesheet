"""The document registry: what a company published, where, and the hash of each file.

Each company directory holds one ``documents.toml``. A document is fetched on demand into
``<raw_root>/<company>/<sha256>.<ext>`` (kept out of version control, and re-fetchable) and
its hash is recorded, so "page 47" always means a page of one identified file.
"""

import hashlib
import tomllib
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from tracesheet.model import CompanyId, FiscalPeriod, Model, PeriodKind
from tracesheet.providers.fetch import Fetcher, FetchError
from tracesheet.providers.toml_out import emit_toml

DOCUMENTS_FILE = "documents.toml"


class DocumentKind(StrEnum):
    ANNUAL_REPORT = "annual_report"
    HALF_YEAR_REPORT = "half_year_report"
    FINANCIAL_STATEMENTS = "financial_statements"
    """A standalone statements-and-notes document published beside the narrative report."""
    STATBOOK = "statbook"
    """The issuer's own spreadsheet of key figures."""
    OFFICIAL_NOTICE = "official_notice"


class Document(Model):
    """One published file: whose, for which period, what kind, and where it lives."""

    company_id: CompanyId
    period: FiscalPeriod
    kind: DocumentKind
    url: str
    language: str = "en"
    sha256: str | None = None
    """Absent until the file has been fetched once."""
    fetched_at: AwareDatetime | None = None
    note: str | None = None


class DocumentsError(ValueError):
    """A documents file is wrong. The message names the file."""


# --- The file's shape, lax so that TOML's own types are accepted. Unknown keys are refused.


class _Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    period: dict[str, object]
    kind: DocumentKind
    url: str
    language: str = "en"
    sha256: str | None = None
    fetched_at: AwareDatetime | None = None
    note: str | None = None


class _File(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[_Entry, ...]


class DocumentRegistry:
    """Reads and rewrites ``<root>/<company-id>/documents.toml``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def documents(self, company: CompanyId) -> tuple[Document, ...]:
        """Every registered document of one company, oldest period first."""
        path = self._path(company)
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            parsed = _File.model_validate(data)
            documents = [self._build(company, entry) for entry in parsed.documents]
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
            msg = f"{path}: {error}"
            raise DocumentsError(msg) from error
        documents.sort(key=lambda d: (d.period.end, d.kind.value))
        return tuple(documents)

    def document(
        self, company: CompanyId, *, period_end: date, kind: DocumentKind
    ) -> Document | None:
        """The document of this kind for the period ending on ``period_end``, if registered."""
        for doc in self.documents(company):
            if doc.period.end == period_end and doc.kind is kind:
                return doc
        return None

    def path_for(self, company: CompanyId, document: Document, raw_root: Path) -> Path:
        """Where a fetched document is stored. Refused for one never fetched."""
        if document.sha256 is None:
            msg = f"{document.url} has not been fetched yet, so it has no path"
            raise FetchError(msg)
        return raw_root / company / f"{document.sha256}{_extension(document.url)}"

    def fetch(
        self, company: CompanyId, document: Document, fetcher: Fetcher, *, raw_root: Path
    ) -> Path:
        """The local file for a document: downloaded once, named by its hash, hash checked.

        A document already on disk is returned without a download. On a document's first
        fetch the hash is written back into ``documents.toml``; on a later one, bytes that
        hash differently from the recorded value are refused.
        """
        if document.sha256 is not None:
            existing = self.path_for(company, document, raw_root)
            if existing.is_file():
                return existing
        content = fetcher(document.url, {})
        digest = hashlib.sha256(content).hexdigest()
        if document.sha256 is not None and digest != document.sha256:
            msg = f"{document.url}: sha256 {digest} does not match the recorded {document.sha256}"
            raise FetchError(msg)
        target = raw_root / company / f"{digest}{_extension(document.url)}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if document.sha256 is None:
            self._record(company, document, digest, datetime.now(tz=UTC))
        return target

    # --- Internals ---

    def _path(self, company: CompanyId) -> Path:
        return self.root / company / DOCUMENTS_FILE

    @staticmethod
    def _build(company: CompanyId, entry: _Entry) -> Document:
        period = FiscalPeriod.model_validate(
            {
                "start": entry.period.get("start"),
                "end": entry.period.get("end"),
                "kind": PeriodKind(str(entry.period.get("kind"))),
            }
        )
        return Document(
            company_id=company,
            period=period,
            kind=entry.kind,
            url=entry.url,
            language=entry.language,
            sha256=entry.sha256,
            fetched_at=entry.fetched_at,
            note=entry.note,
        )

    def _record(
        self, company: CompanyId, document: Document, digest: str, fetched_at: datetime
    ) -> None:
        updated = [
            doc.model_copy(update={"sha256": digest, "fetched_at": fetched_at})
            if doc.url == document.url and doc.period == document.period
            else doc
            for doc in self.documents(company)
        ]
        self._path(company).write_text(
            emit_toml({"documents": [_entry_dict(doc) for doc in updated]}), encoding="utf-8"
        )


def _entry_dict(doc: Document) -> dict[str, object]:
    return {
        "period": {
            "start": doc.period.start,
            "end": doc.period.end,
            "kind": doc.period.kind.value,
        },
        "kind": doc.kind.value,
        "url": doc.url,
        "language": doc.language,
        "sha256": doc.sha256,
        "fetched_at": doc.fetched_at,
        "note": doc.note,
    }


def _extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".pdf", ".xlsx", ".xls", ".html", ".htm"} else ".bin"
