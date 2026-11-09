"""The normalization stage: filed figures in, comparable figures out.

``normalize`` is the only producer of ``Normalized``. Restatements are selected line by line
as of a date; the annual and interim series are kept apart; gaps are reported and irregular
years marked; per-share figures and share counts are put on the share basis of the date;
lines a report did not print are solved from the ones it did; money is converted at the
average rate for flows and the closing rate for balances when asked.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from tracesheet.model import (
    STATEMENT,
    Adjustment,
    AdjustmentKind,
    Company,
    CorporateAction,
    Currency,
    FinancialRecord,
    FiscalPeriod,
    LineItemName,
    Money,
    Normalized,
    PeriodFigures,
    PeriodKind,
    PriceObservation,
    RecordRef,
    Statement,
    Traced,
)
from tracesheet.model.traced import convert, trace
from tracesheet.normalize.rates import YearRates, find_rates
from tracesheet.normalize.rounding import within_rounding
from tracesheet.normalize.shares import ShareBasis
from tracesheet.normalize.standardize import standardize

_ANNUAL_DAYS = (350, 380)


class NormalizationError(ValueError):
    """Normalization could not proceed. The message says what is missing or wrong."""


def normalize(  # noqa: PLR0913 - the options are keyword-only, and each is documented
    company: Company,
    records: Sequence[FinancialRecord],
    as_of: datetime,
    *,
    target_currency: Currency | None = None,
    rates: Sequence[YearRates] = (),
    actions: Sequence[CorporateAction] = (),
    prices: Sequence[PriceObservation] = (),
) -> Normalized:
    """Comparable figures for one company, knowing only what was filed by ``as_of``.

    ``target_currency`` converts every amount, using ``rates`` for each fiscal year; it
    defaults to the company's own currency. ``actions`` are the company's share-basis
    actions: the confirmed ones put per-share figures and counts on the basis of ``as_of``.
    ``prices`` supply the cum-rights close a rights issue without a printed factor needs."""
    currency = target_currency or company.currency
    basis = ShareBasis(company, actions, as_of, prices)
    adjustments: list[Adjustment] = []
    knowable: list[FinancialRecord] = []
    for record in records:
        if record.company_id != company.id:
            msg = f"record {record.id} is of {record.company_id}, not {company.id}"
            raise NormalizationError(msg)
        if record.filed_at > as_of:
            adjustments.append(
                Adjustment(
                    kind=AdjustmentKind.EXCLUDED_AFTER_AS_OF,
                    period=record.period,
                    detail=(
                        f"{record.id} was filed {record.filed_at.date().isoformat()}, after "
                        f"{as_of.date().isoformat()}, and is not used: it was not knowable then"
                    ),
                )
            )
        else:
            knowable.append(record)

    groups: dict[FiscalPeriod, list[FinancialRecord]] = defaultdict(list)
    for record in knowable:
        groups[record.period].append(record)

    used: list[RecordRef] = []
    years: list[PeriodFigures] = []
    interim: list[PeriodFigures] = []
    for period in sorted(groups, key=lambda p: (p.end, p.start)):
        block, contributors, notes = _select(groups[period], period, currency, rates, basis)
        adjustments.extend(notes)
        block, calculation = standardize(block, _label(period))
        if calculation is not None:
            adjustments.append(calculation)
        adjustments.extend(basis.period_notes(period))
        used.extend(r.ref() for r in contributors if r.ref() not in used)
        if period.kind is PeriodKind.ANNUAL:
            block, notes = _check_annual(block, company)
            adjustments.extend(notes)
            years.append(block)
        else:
            interim.append(block)

    fiscal_years = {b.fiscal_year for b in years}
    for missing in sorted(
        y
        for y in range(min(fiscal_years, default=0), max(fiscal_years, default=-1) + 1)
        if y not in fiscal_years
    ):
        adjustments.append(
            Adjustment(
                kind=AdjustmentKind.GAP,
                detail=f"no annual filing for fiscal {missing}: a gap, left empty",
            )
        )

    adjustments.extend(basis.company_notes(min((r.period.start for r in knowable), default=None)))

    return Normalized(
        company_id=company.id,
        as_of=as_of,
        currency=currency,
        years=tuple(years),
        interim=tuple(interim),
        used=tuple(used),
        adjustments=tuple(sorted(adjustments, key=_adjustment_order)),
    )


# --- Internals ---


def _select(
    filings: list[FinancialRecord],
    period: FiscalPeriod,
    currency: Currency,
    rates: Sequence[YearRates],
    basis: ShareBasis,
) -> tuple[PeriodFigures, list[FinancialRecord], list[Adjustment]]:
    """For each line, the latest knowable filing that carries it, on the share basis of
    the date."""
    latest_first = sorted(filings, key=lambda r: r.filed_at, reverse=True)
    original = latest_first[-1]
    chosen: dict[LineItemName, FinancialRecord] = {}
    for record in latest_first:
        for item in record.line_items:
            chosen.setdefault(item.name, record)
    kept: dict[str, list[LineItemName]] = defaultdict(list)
    for name, latest in list(chosen.items()):
        finer = _finer_within_rounding(name, latest, latest_first)
        if finer is not None:
            chosen[name] = finer
            kept[finer.id].append(name)
    figures: dict[LineItemName, Traced] = {}
    converted: list[LineItemName] = []
    for name in sorted(chosen, key=lambda n: n.value):
        record = chosen[name]
        item = next(i for i in record.line_items if i.name is name)
        leaf = basis.adjust(record, item, trace(record, name))
        figures[name], was_converted = _in_currency(leaf, name, period, currency, rates)
        if was_converted:
            converted.append(name)

    notes: list[Adjustment] = []
    by_record: dict[str, list[LineItemName]] = defaultdict(list)
    for name, record in chosen.items():
        by_record[record.id].append(name)
    for rid, lines in kept.items():
        notes.append(
            Adjustment(
                kind=AdjustmentKind.FINER_PRECISION_KEPT,
                period=period,
                detail=(
                    f"{_label(period)}: {_lines(lines)} kept from {rid}; a later report "
                    "re-printed them unchanged or within its own rounding"
                ),
            )
        )
    restated = [(rid, lines) for rid, lines in by_record.items() if rid != original.id]
    for rid, lines in restated:
        notes.append(
            Adjustment(
                kind=AdjustmentKind.RESTATEMENT_USED,
                period=period,
                detail=f"{_label(period)}: {_lines(lines)} taken from the restatement {rid}",
            )
        )
    if len(by_record) > 1:
        mix = "; ".join(f"{len(lines)} from {rid}" for rid, lines in by_record.items())
        notes.append(
            Adjustment(
                kind=AdjustmentKind.MIXED_FILINGS,
                period=period,
                detail=f"{_label(period)}: figures come from more than one filing: {mix}",
            )
        )
    if converted:
        notes.append(
            Adjustment(
                kind=AdjustmentKind.CURRENCY_CONVERTED,
                period=period,
                detail=(
                    f"{_label(period)}: {len(converted)} lines converted to {currency}; flows at "
                    f"the year's average rate, balances at the closing rate"
                ),
            )
        )
    contributors = [r for r in latest_first if r.id in by_record]
    return PeriodFigures(period=period, figures=figures), contributors, notes


def _finer_within_rounding(
    name: LineItemName, latest: FinancialRecord, latest_first: Sequence[FinancialRecord]
) -> FinancialRecord | None:
    """The earlier filing to take a line from instead of the latest: one whose figure the
    latest re-printed within its own rounding, at the same or a finer precision. The finest,
    then the earliest, wins: a re-print that changes nothing is not a restatement. None when
    the latest stands: a real restatement, or no earlier print of the line."""
    head = next(i for i in latest.line_items if i.name is name)
    best: tuple[Decimal, FinancialRecord] | None = None
    for record in latest_first:
        if record.filed_at >= latest.filed_at:
            continue
        item = next((i for i in record.line_items if i.name is name), None)
        if item is None or item.precision is None or head.precision is None:
            continue
        if item.precision > head.precision:
            continue
        if not within_rounding(head.value, head.precision, item.value, item.precision):
            continue
        if best is None or item.precision <= best[0]:
            best = (item.precision, record)
    return None if best is None else best[1]


def _in_currency(
    leaf: Traced,
    name: LineItemName,
    period: FiscalPeriod,
    currency: Currency,
    rates: Sequence[YearRates],
) -> tuple[Traced, bool]:
    if not isinstance(leaf.value, Money) or leaf.value.currency is currency:
        return leaf, False
    year_rates = find_rates(rates, leaf.value.currency, currency, period.fiscal_year)
    if year_rates is None:
        msg = (
            f"{_label(period)} {name} is in {leaf.value.currency} and the target is {currency}, "
            f"but no {leaf.value.currency}/{currency} rates were given for fiscal "
            f"{period.fiscal_year}"
        )
        raise NormalizationError(msg)
    rate = year_rates.closing if STATEMENT[name] is Statement.BALANCE_SHEET else year_rates.average
    return convert(leaf, rate), True


def _check_annual(block: PeriodFigures, company: Company) -> tuple[PeriodFigures, list[Adjustment]]:
    notes: list[Adjustment] = []
    period = block.period
    length = (period.end - period.start).days + 1
    irregular = not _ANNUAL_DAYS[0] <= length <= _ANNUAL_DAYS[1]
    if irregular:
        notes.append(
            Adjustment(
                kind=AdjustmentKind.IRREGULAR_PERIOD,
                period=period,
                detail=(
                    f"{_label(period)} covers {length} days, not a normal year: kept, marked "
                    f"irregular; growth across it is not like for like"
                ),
            )
        )
        block = block.model_copy(update={"irregular": True})
    year_end = company.fiscal_year_end
    if (period.end.month, period.end.day) != (year_end.month, year_end.day):
        notes.append(
            Adjustment(
                kind=AdjustmentKind.YEAR_END_MISMATCH,
                period=period,
                detail=(
                    f"{_label(period)} ends {period.end.isoformat()}, but the company's fiscal "
                    f"year end is {year_end.day} "
                    f"{period.end.replace(month=year_end.month, day=1):%B}"
                ),
            )
        )
    return block, notes


def _label(period: FiscalPeriod) -> str:
    if period.kind is PeriodKind.ANNUAL:
        return f"FY{period.fiscal_year}"
    return f"{period.kind.value.replace('_', '-')} to {period.end.isoformat()}"


def _lines(names: Sequence[LineItemName]) -> str:
    return ", ".join(n.value for n in names)


def _adjustment_order(adjustment: Adjustment) -> tuple[str, str, str]:
    end = adjustment.period.end.isoformat() if adjustment.period else ""
    return (end, adjustment.kind.value, adjustment.detail)
