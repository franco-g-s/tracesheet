"""From an evaluation to a page: every figure formatted, every origin listed once.

The page follows the sheet's order: growth, profitability, cash generation, balance sheet and
shareholder returns, each holding its catalogue measures in catalogue order. The per-share
measures have no section of their own on the sheet and close the shareholder returns table.
Compound growth sits beside growth, and the multiples come after the tables.

Every figure's trail is walked down to its leaves. Each leaf becomes one entry in Sources,
keyed by the start of its content fingerprint, and every cell lists the entries beneath it.
"""

from collections.abc import Iterable, Mapping
from datetime import date

from tracesheet.metrics.catalogue import (
    CAGR_KEYS,
    CAGR_SPANS,
    CATALOGUE,
    CONVENTIONS,
    Kind,
    MetricDef,
    Section,
)
from tracesheet.model import (
    Currency,
    Evaluation,
    Filed,
    MetricValue,
    Multiples,
    NotMeaningful,
    Observed,
    Traced,
)
from tracesheet.multiples import MULTIPLE_KEYS
from tracesheet.report import format as fmt
from tracesheet.report.page import CagrTable, Cell, Page, Row, SourceEntry, Table

NOT_MEANINGFUL = "n/m"
ID_LENGTH = 12
"""Hex digits of a leaf's fingerprint used as its anchor: short enough to keep the page
light, long enough that a collision among a few thousand leaves is vanishingly unlikely.
A collision is refused rather than resolved silently."""

SECTIONS: tuple[tuple[str, tuple[Section, ...]], ...] = (
    ("Growth", (Section.GROWTH,)),
    ("Profitability", (Section.PROFITABILITY,)),
    ("Cash generation", (Section.CASH,)),
    ("Balance sheet", (Section.BALANCE_SHEET,)),
    ("Shareholder returns", (Section.SHAREHOLDERS, Section.PER_SHARE)),
)
"""Each table's title and the catalogue sections it holds, in the sheet's order."""

GROUP_TITLES: Mapping[Section, str] = {Section.PER_SHARE: "Per share"}
"""The subheading over a catalogue section that shares another section's table."""

MULTIPLE_DEFS: Mapping[str, tuple[str, Kind, str]] = {
    "pe": ("Price to earnings", Kind.MULTIPLE, "Share price ÷ diluted EPS"),
    "ev_ebit": ("EV to EBIT", Kind.MULTIPLE, "Enterprise value ÷ EBIT"),
    "ev_ebitda": ("EV to EBITDA", Kind.MULTIPLE, "Enterprise value ÷ EBITDA"),
    "fcf_yield": ("Free cash flow yield", Kind.PERCENT, "Free cash flow ÷ market capitalisation"),
    "pb": ("Price to book", Kind.MULTIPLE, "Share price ÷ book value per share"),
    "dividend_yield": ("Dividend yield", Kind.PERCENT, "Dividend per share ÷ share price"),
}
"""Label, kind and formula of each multiple, keyed as the multiples stage keys them."""


class SourceIdCollisionError(ValueError):
    """Two different leaves share the same shortened fingerprint."""


class _Sources:
    """Collects every leaf under the page's figures, once each."""

    def __init__(self) -> None:
        self.leaves: dict[str, Traced] = {}

    def ids(self, figure: Traced) -> tuple[str, ...]:
        found: list[str] = []
        for leaf in _leaves(figure):
            short = leaf.id[:ID_LENGTH]
            known = self.leaves.setdefault(short, leaf)
            if known.id != leaf.id:
                msg = f"leaves {known.id} and {leaf.id} share the anchor {short}"
                raise SourceIdCollisionError(msg)
            if short not in found:
                found.append(short)
        return tuple(found)

    def entries(self) -> tuple[SourceEntry, ...]:
        entries = [_entry(short, leaf) for short, leaf in self.leaves.items()]
        filed = sorted(
            (e for e in entries if not e.observed),
            key=lambda e: (e.fiscal_year or 0, e.document, e.page or 0, e.line, e.id),
        )
        observed = sorted((e for e in entries if e.observed), key=lambda e: (e.line, e.id))
        return (*filed, *observed)


def build_page(evaluation: Evaluation) -> Page:
    """Lay out one evaluation as a page. Reads the evaluation only; adds no figures."""
    company = evaluation.company
    currency = company.currency
    sources = _Sources()
    years = tuple(y.fiscal_year for y in evaluation.metrics.years)
    by_year = [y.values for y in evaluation.metrics.years]

    tables: list[Table] = []
    for title, sections in SECTIONS:
        rows: list[Row] = []
        for metric in (m for m in CATALOGUE if m.section in sections):
            values = [year.get(metric.key) for year in by_year]
            decimals = fmt.amount_decimals(v for v in values if isinstance(v, Traced))
            starts_group = metric.section is not sections[0] and not any(r.group for r in rows)
            rows.append(
                Row(
                    key=metric.key,
                    label=metric.label,
                    formula=metric.formula,
                    unit=fmt.unit_caption(metric.kind, currency),
                    group=GROUP_TITLES[metric.section] if starts_group else None,
                    cells=tuple(
                        _cell(value, metric.kind, currency, sources, decimals) for value in values
                    ),
                )
            )
        tables.append(Table(section=sections[0], title=title, years=years, rows=tuple(rows)))

    multiples = evaluation.multiples
    return Page(
        title=f"{company.name}: evaluation sheet as of {_long_date(evaluation.as_of.date())}",
        company=company,
        as_of=evaluation.as_of.date(),
        created_at=evaluation.created_at.date(),
        code_version=evaluation.code_version,
        years=years,
        tables=tuple(tables),
        cagr=_cagr(evaluation, currency, sources),
        multiples=None if multiples is None else _multiples(multiples, currency, sources),
        multiples_note=_multiples_note(multiples),
        conventions=CONVENTIONS,
        sources=sources.entries(),
        tie_out=tuple(sorted((str(k), tuple(v)) for k, v in evaluation.tie_out.items())),
    )


def _cell(
    value: MetricValue | None,
    kind: Kind,
    currency: Currency,
    sources: _Sources,
    decimals: int | None = None,
) -> Cell:
    if value is None:
        return Cell(text=NOT_MEANINGFUL, note="not computed for this year")
    if isinstance(value, NotMeaningful):
        return Cell(text=NOT_MEANINGFUL, note=value.reason)
    return Cell(text=fmt.cell(value, kind, currency, decimals), source_ids=sources.ids(value))


def _plain_cell(value: MetricValue, kind: Kind, sources: _Sources) -> Cell:
    if isinstance(value, NotMeaningful):
        return Cell(text=NOT_MEANINGFUL, note=value.reason)
    return Cell(text=fmt.plain(value, kind), source_ids=sources.ids(value))


def _cagr(evaluation: Evaluation, currency: Currency, sources: _Sources) -> CagrTable | None:
    if not evaluation.metrics.years:
        return None
    defs: dict[str, MetricDef] = {m.key: m for m in CATALOGUE}
    rows = []
    for key in CAGR_KEYS:
        rates = evaluation.metrics.cagr.get(key, {})
        cells = tuple(
            _cell(rates.get(span), Kind.PERCENT, currency, sources) for span in CAGR_SPANS
        )
        rows.append(
            Row(
                key=key,
                label=defs[key].label,
                formula=f"{defs[key].label}: (last ÷ first) ^ (1 ÷ years) − 1",
                unit="%",
                cells=cells,
            )
        )
    return CagrTable(
        end_year=evaluation.metrics.years[-1].fiscal_year, spans=CAGR_SPANS, rows=tuple(rows)
    )


def _multiples(multiples: Multiples, currency: Currency, sources: _Sources) -> Table:
    year = multiples.fiscal_year
    rows = [
        Row(
            key="price",
            label="Share price",
            formula=f"Closing price on {_long_date(multiples.price_date)}",
            cells=(_plain_cell(multiples.price, Kind.PER_SHARE, sources),),
        )
    ]
    if multiples.exchange_rate is not None:
        rows.append(
            Row(
                key="exchange_rate",
                label="Exchange rate",
                formula=f"ECB reference rate into {currency.value} on the price date",
                cells=(
                    Cell(
                        text=fmt.plain(multiples.exchange_rate),
                        source_ids=sources.ids(multiples.exchange_rate),
                    ),
                ),
            )
        )
    rows += [
        Row(
            key="market_cap",
            label="Market capitalisation",
            formula="Share price × year-end shares outstanding, net of treasury shares",
            cells=(_plain_cell(multiples.market_cap, Kind.AMOUNT, sources),),
        ),
        Row(
            key="enterprise_value",
            label="Enterprise value",
            formula="Market capitalisation + net debt + non-controlling interests",
            cells=(_plain_cell(multiples.enterprise_value, Kind.AMOUNT, sources),),
        ),
    ]
    for key in MULTIPLE_KEYS:
        label, kind, formula = MULTIPLE_DEFS[key]
        rows.append(
            Row(
                key=key,
                label=label,
                formula=formula,
                cells=(_plain_cell(multiples.values[key], kind, sources),),
            )
        )
    return Table(section=None, title="Valuation multiples", years=(year,), rows=tuple(rows))


def _multiples_note(multiples: Multiples | None) -> str:
    if multiples is None:
        return (
            "No price available. The sheet was built without a closing share price, so it "
            "has no multiples; every other section stands without one."
        )
    origin = multiples.price.origin
    where = f" Source: {origin.source}." if isinstance(origin, Observed) else ""
    text = (
        f"At the close of {_long_date(multiples.price_date)}, {fmt.plain(multiples.price)}, "
        f"set against fiscal {multiples.fiscal_year}.{where}"
    )
    if multiples.exchange_rate is not None:
        text += f" Converted at {fmt.plain(multiples.exchange_rate)}."
    return text


def _leaves(figure: Traced) -> Iterable[Traced]:
    if figure.origin is not None:
        yield figure
        return
    for node in figure.inputs:
        yield from _leaves(node)


def _entry(short: str, leaf: Traced) -> SourceEntry:
    origin = leaf.origin
    if isinstance(origin, Filed):
        return SourceEntry(
            id=short,
            document=origin.source.reference,
            page=origin.page,
            quote=origin.label,
            line=origin.line_item.value,
            fiscal_year=origin.record.period.fiscal_year,
            sha256=origin.source.sha256,
            dated=origin.record.filed_at.date(),
            note=origin.note,
            not_printed=bool(origin.not_printed),
        )
    assert origin is not None
    return SourceEntry(
        id=short,
        document=origin.source,
        page=None,
        quote=None,
        line=origin.what,
        fiscal_year=None,
        observed=True,
        dated=origin.observed_at.date(),
    )


def _long_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"
