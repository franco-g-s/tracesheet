"""The page model: everything the sheet shows, already formatted, in the order it shows it.

``build_page`` makes one from an evaluation; ``render`` turns it into HTML. Keeping the two
apart means the arithmetic and the wording can be tested without parsing any markup, and the
template has no decisions left to make: it only lays out text it is handed.
"""

from datetime import date

from tracesheet.metrics.catalogue import Section
from tracesheet.model import Company, Model


class Cell(Model):
    """One figure as shown. ``source_ids`` point at entries in ``Page.sources``; ``note`` is
    the reason a figure is "n/m"."""

    text: str
    source_ids: tuple[str, ...] = ()
    note: str | None = None


class Row(Model):
    """One measure across the columns of its table. ``unit`` is the caption every cell in
    the row shares, such as "CHF m" or "%". ``group`` is set on the first row of a run of
    measures from another catalogue section, and is the subheading shown above it."""

    key: str
    label: str
    formula: str
    cells: tuple[Cell, ...]
    unit: str = ""
    group: str | None = None


class Table(Model):
    """One section of measures, with fiscal years as columns, oldest first.

    ``section`` is ``None`` for the price multiples, which are not catalogue measures.
    """

    section: Section | None
    title: str
    years: tuple[int, ...]
    rows: tuple[Row, ...]


class CagrTable(Model):
    """Compound annual growth over each span, all ending in ``end_year``: one cell per span
    in every row."""

    end_year: int
    spans: tuple[int, ...]
    rows: tuple[Row, ...]


class SourceEntry(Model):
    """One origin at the bottom of some figure's trail.

    For a filed figure: ``document`` is the typed-in filing it was read from (with the
    report's fingerprint in ``sha256``), ``page`` the printed page, ``quote`` the report's own
    label for the line, ``line`` the line item it was entered as, and ``dated`` the day the
    report was published. For a market observation (``observed``): ``document`` names where
    it was read, ``line`` what was observed, and ``dated`` the day it refers to.
    """

    id: str
    document: str
    page: int | None
    quote: str | None
    line: str
    fiscal_year: int | None
    observed: bool = False
    sha256: str | None = None
    dated: date | None = None
    note: str | None = None
    not_printed: bool = False
    """The statement prints no such line; the figure is a zero, with a page to check."""


class Page(Model):
    """The whole sheet."""

    title: str
    company: Company
    as_of: date
    created_at: date
    code_version: str
    years: tuple[int, ...]
    tables: tuple[Table, ...]
    cagr: CagrTable | None
    multiples: Table | None
    multiples_note: str
    conventions: tuple[tuple[str, str], ...]
    sources: tuple[SourceEntry, ...]
    tie_out: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Every filing used, by record id, with the accounting identities it fails."""
