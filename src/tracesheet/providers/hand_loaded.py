"""Typed-in figures: numbers read from annual reports and written into TOML files.

One directory per company holds ``company.toml`` (who the company is), ``documents.toml``
(what it published), ``labels.toml`` (its own wording for each line), an optional
``actions.toml`` (share-basis actions confirmed against its documents) and one file per
filing. Every mistake the loader can detect is refused with the file and, where there is
one, the line item named. Unknown keys are refused too, so a misspelt or stray field fails
loudly instead of being ignored.
"""

import tomllib
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictInt,
    ValidationError,
)

from tracesheet.model import (
    COUNT_LINES,
    PER_SHARE_LINES,
    ActionDocument,
    ActionKind,
    AuditOpinion,
    Company,
    CompanyId,
    CorporateAction,
    Currency,
    FinancialRecord,
    FiscalPeriod,
    LineItem,
    LineItemName,
    Listing,
    Money,
    MonthDay,
    PeriodKind,
    RecordId,
    RecordRef,
    ReportingStandard,
    RightsTerms,
    ShareCount,
    Source,
)
from tracesheet.model.market import RATIO_ACTIONS, SHARE_BASIS_ACTIONS
from tracesheet.providers.documents import DOCUMENTS_FILE, DocumentRegistry, DocumentsError
from tracesheet.providers.reconcile import reconcile

COMPANY_FILE = "company.toml"
ACTIONS_FILE = "actions.toml"
LABELS_FILE = "labels.toml"
RESERVED_FILES = frozenset({COMPANY_FILE, DOCUMENTS_FILE, LABELS_FILE, ACTIONS_FILE})
"""Files in a company directory that are not filings: who the company is, what it
published, its wording for each line, and its confirmed share-basis actions."""


class FiguresIn(StrEnum):
    """The scale a report prints in. The loader multiplies out to full units."""

    UNITS = "units"
    THOUSANDS = "thousands"
    MILLIONS = "millions"


_SCALE: dict[FiguresIn, Decimal] = {
    FiguresIn.UNITS: Decimal(1),
    FiguresIn.THOUSANDS: Decimal(1_000),
    FiguresIn.MILLIONS: Decimal(1_000_000),
}


class HandLoadedError(ValueError):
    """Something in a typed-in file is wrong. Names the file, and the line item if any."""

    def __init__(self, file: Path, detail: str, line_item: str | None = None) -> None:
        self.file = file
        self.line_item = line_item
        where = f"{file}" if line_item is None else f"{file}, line item {line_item}"
        super().__init__(f"{where}: {detail}")


# --- Parsing models: the shape of a file, lax so that TOML's plain strings are accepted.
# The strict domain models are built from these. Lax mode never lets a number into a str
# field, so an unquoted amount is still refused.


def _quoted(value: object) -> object:
    if not isinstance(value, str):
        msg = "must be written in quotes, as text; a bare number would be read as a float"
        raise ValueError(msg)
    return value


def _upper(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


NOT_PRINTED_NOTE = "not printed: the statement on this page has no such line, so none"
"""The note a line declared not printed carries when the typist wrote none."""


class _File(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _LineItemEntry(_File):
    name: LineItemName
    value: Annotated[str, BeforeValidator(_quoted)]
    label: str | None = None
    page: int
    pdf_page: int | None = None
    figures_in: FiguresIn | None = None
    note: str | None = None
    share_basis_date: date | None = None
    share_class: str | None = None
    not_printed: bool = False


class _PeriodEntry(_File):
    start: date
    end: date
    kind: PeriodKind


class _SourceEntry(_File):
    document: str
    url: str | None = None
    sha256: str | None = None


class _RecordFile(_File):
    company: str
    period: _PeriodEntry
    filed_at: AwareDatetime
    currency: Annotated[Currency, BeforeValidator(_upper)]
    figures_in: FiguresIn
    source: _SourceEntry
    line_items: tuple[_LineItemEntry, ...]
    restates: str | None = None
    auditor: str | None = None
    audit_opinion: AuditOpinion | None = None
    going_concern_emphasis: bool = False


class _CompanyFile(_File):
    id: str
    name: str
    listing: Listing
    currency: Annotated[Currency, BeforeValidator(_upper)]
    reporting_standard: ReportingStandard
    domicile_country: Annotated[str, BeforeValidator(_upper)]
    fiscal_year_end: MonthDay
    delisted_at: AwareDatetime | None = None
    share_classes: tuple[str, ...] | None = None


class _ActionSourceEntry(_File):
    document: str
    sha256: str
    page: StrictInt
    pdf_page: StrictInt | None = None


class _RightsEntry(_File):
    offered_shares: StrictInt
    held_shares: StrictInt
    subscription_price: Annotated[str, BeforeValidator(_quoted)]


class _ActionEntry(_File):
    kind: ActionKind
    effective: date
    share_class: str | None = None
    into_class: str | None = None
    new_shares: StrictInt | None = None
    old_shares: StrictInt | None = None
    printed_factor: Annotated[str, BeforeValidator(_quoted)] | None = None
    rights: _RightsEntry | None = None
    source: _ActionSourceEntry
    quote: str
    note: str | None = None


class _ActionsFile(_File):
    actions: tuple[_ActionEntry, ...] = ()


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'file'}: {item['msg']}"
        for item in error.errors()
    )


def _line_item_in(error: ValidationError, entries: list[Any]) -> str | None:
    """Which line item a validation error points at, by name if the name parsed."""
    for item in error.errors():
        loc = item["loc"]
        if len(loc) >= 2 and loc[0] == "line_items" and isinstance(loc[1], int):
            index = loc[1]
            entry = entries[index] if index < len(entries) else None
            name = entry.get("name") if isinstance(entry, dict) else None
            return str(name) if name is not None else f"#{index + 1}"
    return None


class HandLoaded:
    """Reads ``<root>/<company-id>/company.toml`` and ``<root>/<company-id>/<record-id>.toml``.

    Every subdirectory of ``root`` is a company and must hold a ``company.toml``.
    """

    name = "hand-loaded"

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- Provider protocol ---

    def companies(self) -> tuple[CompanyId, ...]:
        """The companies under ``root``, in directory-name order."""
        found: list[CompanyId] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / COMPANY_FILE).is_file():
                raise HandLoadedError(entry, f"a company directory needs a {COMPANY_FILE}")
            found.append(CompanyId(entry.name))
        return tuple(found)

    def financial_records(self, company: CompanyId) -> tuple[FinancialRecord, ...]:
        """Every filing of one company, oldest period first, each one tied out."""
        directory = self._directory(company)
        files = {
            path.stem: (path, self._parse(_RecordFile, path))
            for path in sorted(directory.glob("*.toml"))
            if path.name not in RESERVED_FILES
        }
        records = [
            self._build_record(path, parsed, files, company) for path, parsed in files.values()
        ]
        classes = self.company(company).share_classes
        for (path, _), record in zip(files.values(), records, strict=True):
            for item in record.line_items:
                if item.share_class is not None and item.share_class not in classes:
                    raise HandLoadedError(
                        path,
                        f"unknown share class {item.share_class!r}; the company has {classes}",
                        item.name,
                    )
        records.sort(key=lambda record: (record.period.end, record.filed_at))
        return tuple(records)

    # --- Reference data, outside the provider protocol ---

    def company(self, company: CompanyId) -> Company:
        """Who the company is, from its ``company.toml``."""
        path = self._directory(company) / COMPANY_FILE
        parsed = self._parse(_CompanyFile, path)
        if parsed.id != company:
            raise HandLoadedError(
                path, f"says id = {parsed.id!r} but sits in directory {company!r}"
            )
        try:
            return Company(
                id=CompanyId(parsed.id),
                name=parsed.name,
                listing=parsed.listing,
                currency=parsed.currency,
                reporting_standard=parsed.reporting_standard,
                domicile_country=parsed.domicile_country,
                fiscal_year_end=parsed.fiscal_year_end,
                delisted_at=parsed.delisted_at,
                **(
                    {"share_classes": parsed.share_classes}
                    if parsed.share_classes is not None
                    else {}
                ),
            )
        except ValidationError as error:
            raise HandLoadedError(path, _describe(error)) from error

    def actions(self, company: CompanyId) -> tuple[CorporateAction, ...]:
        """The share-basis actions confirmed against the issuer's documents, from
        ``actions.toml``, oldest first. Empty when the file is absent.

        Each action cites a document registered in ``documents.toml`` by its hash, with the
        page and the sentence that states it.
        """
        path = self._directory(company) / ACTIONS_FILE
        if not path.is_file():
            return ()
        owner = self.company(company)
        parsed = self._parse(_ActionsFile, path)
        try:
            registered = {
                d.sha256 for d in DocumentRegistry(self.root).documents(company) if d.sha256
            }
        except DocumentsError as error:
            raise HandLoadedError(path, f"its documents cannot be read: {error}") from error
        actions = [
            self._build_action(path, index, entry, owner, registered)
            for index, entry in enumerate(parsed.actions, start=1)
        ]
        actions.sort(key=lambda a: a.ex_date)
        return tuple(actions)

    # --- Internals ---

    def _directory(self, company: CompanyId) -> Path:
        directory = self.root / company
        if not (directory / COMPANY_FILE).is_file():
            raise HandLoadedError(directory, f"no such company here: no {COMPANY_FILE}")
        return directory

    def _parse[F: _File](self, model: type[F], path: Path) -> F:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise HandLoadedError(path, f"cannot be read: {error.strerror}") from error
        except tomllib.TOMLDecodeError as error:
            raise HandLoadedError(path, f"is not valid TOML: {error}") from error
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raw_entries = data.get("line_items")
            entries: list[Any] = raw_entries if isinstance(raw_entries, list) else []
            raise HandLoadedError(path, _describe(error), _line_item_in(error, entries)) from error

    def _build_record(
        self,
        path: Path,
        parsed: _RecordFile,
        siblings: dict[str, tuple[Path, _RecordFile]],
        company: CompanyId,
    ) -> FinancialRecord:
        if parsed.company != company:
            raise HandLoadedError(
                path, f"says company = {parsed.company!r} but sits in {company!r}"
            )
        period = FiscalPeriod(
            start=parsed.period.start, end=parsed.period.end, kind=parsed.period.kind
        )
        items = tuple(self._build_line_item(path, entry, parsed) for entry in parsed.line_items)
        try:
            record = FinancialRecord(
                id=RecordId(path.stem),
                company_id=company,
                period=period,
                filed_at=parsed.filed_at,
                source=Source(
                    provider=self.name,
                    reference=f"{company}/{path.name}",
                    sha256=parsed.source.sha256,
                ),
                line_items=items,
                restates=self._restated(path, parsed, siblings, company),
                auditor=parsed.auditor,
                audit_opinion=parsed.audit_opinion,
                going_concern_emphasis=parsed.going_concern_emphasis,
            )
        except ValidationError as error:
            raise HandLoadedError(path, _describe(error)) from error
        failures = reconcile(
            record, tolerance=Money(amount=_SCALE[parsed.figures_in], currency=parsed.currency)
        )
        if failures:
            raise HandLoadedError(path, "the figures do not tie: " + "; ".join(failures))
        return record

    def _build_line_item(self, path: Path, entry: _LineItemEntry, parsed: _RecordFile) -> LineItem:
        try:
            printed = Decimal(entry.value)
        except InvalidOperation as error:
            raise HandLoadedError(path, f"{entry.value!r} is not a number", entry.name) from error
        if entry.not_printed and entry.label is not None:
            raise HandLoadedError(
                path,
                "a line declared not printed has no label: the page has no such line",
                entry.name,
            )
        if not entry.not_printed and entry.label is None:
            raise HandLoadedError(path, "a printed line needs its label from the page", entry.name)
        scale = entry.figures_in or parsed.figures_in
        if entry.name in PER_SHARE_LINES and scale is not FiguresIn.UNITS:
            raise HandLoadedError(
                path, 'a per share figure is typed in units: add figures_in = "units"', entry.name
            )
        amount = printed * _SCALE[scale]
        exponent = printed.as_tuple().exponent
        precision = Decimal(1).scaleb(exponent if isinstance(exponent, int) else 0) * _SCALE[scale]
        value: Money | ShareCount = (
            ShareCount(count=amount)
            if entry.name in COUNT_LINES
            else Money(amount=amount, currency=parsed.currency)
        )
        try:
            return LineItem(
                name=entry.name,
                value=value,
                label=entry.label,
                page=entry.page,
                pdf_page=entry.pdf_page,
                note=entry.note or (NOT_PRINTED_NOTE if entry.not_printed else None),
                share_basis_date=entry.share_basis_date,
                share_class=entry.share_class,
                not_printed=entry.not_printed,
                precision=precision,
            )
        except ValidationError as error:
            raise HandLoadedError(path, _describe(error), entry.name) from error

    @staticmethod
    def _build_action(
        path: Path,
        index: int,
        entry: _ActionEntry,
        company: Company,
        registered: set[str],
    ) -> CorporateAction:
        where = f"action #{index} ({entry.kind} effective {entry.effective.isoformat()})"

        def refuse(detail: str) -> HandLoadedError:
            return HandLoadedError(path, f"{where}: {detail}")

        if entry.kind not in SHARE_BASIS_ACTIONS:
            raise refuse(f"{ACTIONS_FILE} holds share-basis actions only, not a {entry.kind}")
        if entry.source.sha256 not in registered:
            raise refuse(
                f"its document {entry.source.document!r} ({entry.source.sha256[:12]}…) is not "
                f"in documents.toml; register and fetch it first"
            )
        if entry.kind in RATIO_ACTIONS and not (
            entry.new_shares is not None
            and entry.old_shares is not None
            and entry.new_shares > 0
            and entry.old_shares > 0
        ):
            raise refuse(
                "needs two positive whole numbers from the issuer's document: "
                "new_shares and old_shares"
            )
        if (
            entry.kind is ActionKind.RIGHTS_ISSUE
            and entry.printed_factor is None
            and entry.rights is None
        ):
            raise refuse(
                "a rights issue needs the printed factor the company gives for its EPS, "
                "or its terms"
            )
        classes = company.share_classes
        if entry.share_class is None and len(classes) > 1:
            raise refuse(f"the company has several share classes {classes}: name one")
        share_class = entry.share_class or classes[0]
        for named in (share_class, entry.into_class):
            if named is not None and named not in classes:
                raise refuse(f"unknown share class {named!r}; the company has {classes}")
        try:
            return CorporateAction(
                company_id=company.id,
                kind=entry.kind,
                ex_date=entry.effective,
                new_shares=entry.new_shares,
                old_shares=entry.old_shares,
                printed_factor=(
                    Decimal(entry.printed_factor) if entry.printed_factor is not None else None
                ),
                rights=(
                    RightsTerms(
                        offered_shares=entry.rights.offered_shares,
                        held_shares=entry.rights.held_shares,
                        subscription_price=Money(
                            amount=Decimal(entry.rights.subscription_price),
                            currency=company.currency,
                        ),
                    )
                    if entry.rights is not None
                    else None
                ),
                share_class=share_class,
                into_class=entry.into_class,
                source=f"hand-loaded:{company.id}/{ACTIONS_FILE}",
                document=ActionDocument(
                    document=entry.source.document,
                    sha256=entry.source.sha256,
                    page=entry.source.page,
                    pdf_page=entry.source.pdf_page,
                ),
                quote=entry.quote,
                confirmed_by=f"{company.id}/{ACTIONS_FILE}",
                note=entry.note,
            )
        except (ValidationError, InvalidOperation) as error:
            detail = _describe(error) if isinstance(error, ValidationError) else str(error)
            raise refuse(detail) from error

    @staticmethod
    def _restated(
        path: Path,
        parsed: _RecordFile,
        siblings: dict[str, tuple[Path, _RecordFile]],
        company: CompanyId,
    ) -> RecordRef | None:
        if parsed.restates is None:
            return None
        target = siblings.get(parsed.restates)
        if target is None:
            raise HandLoadedError(
                path, f"restates {parsed.restates!r}, but there is no {parsed.restates}.toml here"
            )
        _, other = target
        return RecordRef(
            id=RecordId(parsed.restates),
            company_id=company,
            period=FiscalPeriod(
                start=other.period.start, end=other.period.end, kind=other.period.kind
            ),
            filed_at=other.filed_at,
        )
