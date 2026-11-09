"""From a page to one self-contained HTML file.

The stylesheet and the script are read from this package and inlined, so the file opens
offline and fetches nothing: no fonts, no libraries, no analytics. Jinja2 escapes every
piece of text it is handed; only the package's own stylesheet and script go in unescaped.
"""

import calendar
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from tracesheet.model import ReportingStandard
from tracesheet.report.page import Page, SourceEntry

TEMPLATES = Path(__file__).resolve().parent / "templates"
RECENT_YEARS = 10
"""How many of the latest fiscal years the "last 10 years" view keeps."""

_STANDARDS = {
    ReportingStandard.IFRS: "IFRS",
    ReportingStandard.US_GAAP: "US GAAP",
    ReportingStandard.SWISS_GAAP_FER: "Swiss GAAP FER",
}
_COUNTRIES = {
    "CH": "Switzerland",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "NL": "Netherlands",
    "US": "United States",
}


@dataclass(frozen=True)
class SourceGroup:
    """Consecutive Sources entries that come from one document."""

    document: str
    observed: bool
    fiscal_year: int | None
    sha256: str | None
    entries: tuple[SourceEntry, ...]


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render(page: Page) -> str:
    """The page as a complete HTML document."""
    older = frozenset(page.years[:-RECENT_YEARS]) if len(page.years) > RECENT_YEARS else frozenset()
    fye = page.company.fiscal_year_end
    numbers = {entry.id: index for index, entry in enumerate(page.sources, start=1)}
    return (
        _environment()
        .get_template("sheet.html.j2")
        .render(
            page=page,
            older=older,
            recent=RECENT_YEARS,
            numbers=numbers,
            groups=_groups(page.sources),
            failing=[record for record, failures in page.tie_out if failures],
            standard=_STANDARDS[page.company.reporting_standard],
            domicile=_COUNTRIES.get(page.company.domicile_country, page.company.domicile_country),
            fiscal_year_end=f"{fye.day} {calendar.month_name[fye.month]}",
            span=_span(page.years),
            long_date=lambda day: f"{day.day} {day:%B %Y}",
            style=Markup((TEMPLATES / "style.css").read_text(encoding="utf-8")),
            script=Markup((TEMPLATES / "script.js").read_text(encoding="utf-8")),
        )
    )


def _span(years: tuple[int, ...]) -> str:
    if not years:
        return "no fiscal years"
    if len(years) == 1:
        return f"fiscal {years[0]}"
    return f"{years[0]}–{years[-1]}, {len(years)} fiscal years"


def _groups(sources: tuple[SourceEntry, ...]) -> tuple[SourceGroup, ...]:
    groups: list[SourceGroup] = []
    for entry in sources:
        last = groups[-1] if groups else None
        if last is not None and (last.document, last.observed) == (entry.document, entry.observed):
            groups[-1] = SourceGroup(
                last.document,
                last.observed,
                last.fiscal_year,
                last.sha256,
                (*last.entries, entry),
            )
        else:
            groups.append(
                SourceGroup(
                    entry.document, entry.observed, entry.fiscal_year, entry.sha256, (entry,)
                )
            )
    return tuple(groups)
