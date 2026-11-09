"""Share-basis normalization: per-share figures and share counts on one basis.

A split, a reverse split, a bonus issue, the bonus element of a rights issue, or two share
classes merging change what one share *is* without changing the business. Across such an
action, every per-share figure and share count stops being comparable with the years before.

This module puts every per-share and count figure on the share basis of ``as_of``:

- only **confirmed** actions change a figure: those typed into the company's actions file
  from the issuer's document, which is what confirms them;
- an action counts only if it is **effective on or before** ``as_of`` (what was knowable)
  and **after the figure's basis date** (a figure already on the new basis is not adjusted
  twice);
- counts are **multiplied** by the factor and per-share figures **divided** by it, through
  the traced operations, so the factor (an ``Observed`` leaf naming the action, its
  document, page and hash) appears in every adjusted figure's trail;
- amounts of money are never touched.

What it did, and what it would not do (a rights issue without a factor, a spin-off, a
company with several live share classes), is said in plain words as adjustments. Pure: no
files, no network, no clock.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal, Inexact, localcontext

from tracesheet.model import (
    COUNT_LINES,
    PER_SHARE_LINES,
    ActionKind,
    Adjustment,
    AdjustmentKind,
    Company,
    CorporateAction,
    FinancialRecord,
    FiscalPeriod,
    LineItem,
    LineItemName,
    PeriodKind,
    PriceObservation,
    Traced,
    Unit,
)
from tracesheet.model.market import RATIO_ACTIONS, SHARE_BASIS_ACTIONS
from tracesheet.model.traced import observed, total

SHARE_LINES = COUNT_LINES | PER_SHARE_LINES
"""The lines a share-basis action changes. Every other line is an amount and is never
touched."""

ADJUSTING = frozenset({*RATIO_ACTIONS, ActionKind.RIGHTS_ISSUE})
"""The kinds that change figures. A spin-off is recorded and stated, never adjusted."""


# --- The basis rule: which actions change one figure ---


def basis_date(record: FinancialRecord, item: LineItem) -> date:
    """The date whose share basis the printed figure is on: the line's own
    ``share_basis_date`` where one was typed, else the record's filing date, because a report
    authorised after a split prints its EPS on the new basis (IAS 33.64)."""
    if item.share_basis_date is not None:
        return item.share_basis_date
    return record.filed_at.date()


def in_window(record: FinancialRecord, item: LineItem, action: CorporateAction) -> bool:
    """The action took effect between this filing's period end and its filing date, and
    the line relies on the default basis. Such a figure is pointed out for a person to check.

    Only a record's own period counts: a restatement's comparative column is on the basis
    of its filing, as IAS 33.64 has every period presented restated, so a pre-split count
    printed there needs its own ``share_basis_date``."""
    return (
        record.restates is None
        and item.share_basis_date is None
        and record.period.end < action.ex_date <= record.filed_at.date()
    )


def applicable(
    record: FinancialRecord,
    item: LineItem,
    actions: Iterable[CorporateAction],
    as_of: date,
    default_class: str,
) -> tuple[CorporateAction, ...]:
    """The confirmed actions that change this figure's basis, oldest first.

    Effective on or before ``as_of``, and after the figure's basis date, with one exception:
    the year-end count of a filing made after an action that followed its period end is a
    fact about the balance-sheet date, and so still on the old basis. A class unification
    moves the figure to the surviving class, whose later actions then apply.
    """
    if item.name not in SHARE_LINES:
        return ()
    base = basis_date(record, item)
    current = item.share_class or default_class
    found: list[CorporateAction] = []
    for action in sorted(actions, key=lambda a: a.ex_date):
        if not action.confirmed or action.kind not in ADJUSTING or action.ex_date > as_of:
            continue
        after_basis = action.ex_date > base or (
            item.name is LineItemName.SHARES_OUTSTANDING and in_window(record, item, action)
        )
        if not after_basis or (action.share_class or default_class) != current:
            continue
        found.append(action)
        if action.kind is ActionKind.CLASS_UNIFICATION:
            assert action.into_class is not None
            current = action.into_class
    return tuple(found)


def live_classes(
    company: Company, actions: Iterable[CorporateAction], as_of: date
) -> tuple[str, ...]:
    """The company's share classes still listed on ``as_of``: every declared class but
    those a confirmed unification retired by then."""
    retired = {
        a.share_class
        for a in actions
        if a.confirmed and a.kind is ActionKind.CLASS_UNIFICATION and a.ex_date <= as_of
    }
    return tuple(c for c in company.share_classes if c not in retired)


# --- The factor: an Observed leaf, or a traced derivation from prices ---


@dataclass(frozen=True)
class Factor:
    """One action's factor as traced numbers. A single leaf where new ÷ old is exact; the
    two whole numbers as two leaves where it is not, so a 2-for-3 stays exact."""

    action: CorporateAction
    single: Traced | None = None
    new: Traced | None = None
    old: Traced | None = None

    @property
    def display(self) -> str:
        if self.single is not None:
            assert isinstance(self.single.value, Decimal)
            return _plain(self.single.value)
        assert self.new is not None and self.old is not None
        return f"{_plain(_ratio(self.new))}/{_plain(_ratio(self.old))}"

    def apply(self, figure: Traced, line: LineItemName) -> Traced:
        """Counts multiplied by the factor, per-share figures divided by it."""
        count = line in COUNT_LINES
        if self.single is not None:
            return figure * self.single if count else figure / self.single
        assert self.new is not None and self.old is not None
        return (figure * self.new) / self.old if count else (figure * self.old) / self.new


def factor(action: CorporateAction, prices: Sequence[PriceObservation] = ()) -> Factor | None:
    """The action's factor, or None where it cannot be derived yet: a rights issue with
    neither a printed factor nor both its terms and a cum-rights close. Never guessed."""
    when = datetime.combine(action.ex_date, time(0), tzinfo=UTC)
    source = _document(action)
    name = describe(action)
    if action.kind in RATIO_ACTIONS:
        assert action.new_shares is not None and action.old_shares is not None
        new, old = Decimal(action.new_shares), Decimal(action.old_shares)
        quotient = _exact_quotient(new, old)
        if quotient is not None:
            leaf = observed(
                quotient,
                Unit.RATIO,
                what=f"factor {_plain(quotient)}, {name}",
                source=source,
                observed_at=when,
            )
            return Factor(action=action, single=leaf)
        return Factor(
            action=action,
            new=observed(
                new, Unit.RATIO, what=f"new shares, {name}", source=source, observed_at=when
            ),
            old=observed(
                old, Unit.RATIO, what=f"old shares, {name}", source=source, observed_at=when
            ),
        )
    if action.kind is ActionKind.RIGHTS_ISSUE:
        if action.printed_factor is not None:
            leaf = observed(
                action.printed_factor,
                Unit.RATIO,
                what=f"printed factor, {name}",
                source=source,
                observed_at=when,
            )
            return Factor(action=action, single=leaf)
        return _rights_factor(action, prices, source=source, name=name, when=when)
    return None


def _rights_factor(
    action: CorporateAction,
    prices: Sequence[PriceObservation],
    *,
    source: str,
    name: str,
    when: datetime,
) -> Factor | None:
    """IAS 33 A2: the fair value per share just before the rights are exercised, divided by
    the theoretical ex-rights price, (held * close + offered * subscription) ÷ (held +
    offered). Every input a leaf; the factor a traced derivation."""
    terms = action.rights
    before = [p for p in prices if p.company_id == action.company_id and p.date < action.ex_date]
    if terms is None or not before:
        return None
    last = max(before, key=lambda p: p.date)
    close = observed(
        last.close,
        Unit.PER_SHARE,
        what=f"last cum-rights close {last.date.isoformat()}",
        source=last.source,
        observed_at=last.retrieved_at,
    )
    subscription = observed(
        terms.subscription_price,
        Unit.PER_SHARE,
        what=f"subscription price, {name}",
        source=source,
        observed_at=when,
    )
    held = observed(
        Decimal(terms.held_shares),
        Unit.RATIO,
        what=f"shares held per lot, {name}",
        source=source,
        observed_at=when,
    )
    offered = observed(
        Decimal(terms.offered_shares),
        Unit.RATIO,
        what=f"new shares offered per lot, {name}",
        source=source,
        observed_at=when,
    )
    ex_rights = total(held * close, offered * subscription) / (held + offered)
    return Factor(action=action, single=close / ex_rights)


# --- The stage's helper: one call per figure, notes per period and per company ---


@dataclass
class _PeriodLog:
    adjusted: dict[int, list[LineItemName]] = field(default_factory=lambda: defaultdict(list))
    not_adjusted: dict[int, list[LineItemName]] = field(default_factory=lambda: defaultdict(list))
    window: dict[int, list[LineItemName]] = field(default_factory=lambda: defaultdict(list))


class ShareBasis:
    """Share-basis normalization for one company as of one date.

    Only the company's own confirmed share-basis actions are used. An action without
    ``confirmed_by`` has not been checked against the issuer's document and is ignored;
    the typed-in figures provider confirms every action in the actions file."""

    def __init__(
        self,
        company: Company,
        actions: Sequence[CorporateAction],
        as_of: datetime,
        prices: Sequence[PriceObservation] = (),
    ) -> None:
        self.company = company
        self.as_of = as_of
        self.day = as_of.date()
        own = [a for a in actions if a.company_id == company.id and a.kind in SHARE_BASIS_ACTIONS]
        self.confirmed = tuple(sorted((a for a in own if a.confirmed), key=lambda a: a.ex_date))
        self.live = live_classes(company, self.confirmed, self.day)
        self.multi_class = len(self.live) > 1
        self.default_class = self.live[0] if len(self.live) == 1 else company.share_classes[0]
        self._factors = {id(a): factor(a, prices) for a in self.confirmed}
        self._index = {id(a): i for i, a in enumerate(self.confirmed)}
        self._logs: dict[FiscalPeriod, _PeriodLog] = defaultdict(_PeriodLog)

    def adjust(self, record: FinancialRecord, item: LineItem, figure: Traced) -> Traced:
        """The figure on the share basis of ``as_of``; unchanged for an amount line, or for
        every line of a company with several live share classes."""
        if item.name not in SHARE_LINES or self.multi_class:
            return figure
        log = self._logs[record.period]
        for action in self.confirmed:
            if (
                action.kind in ADJUSTING
                and action.ex_date <= self.day
                and in_window(record, item, action)
            ):
                log.window[self._index[id(action)]].append(item.name)
        for action in applicable(record, item, self.confirmed, self.day, self.default_class):
            found = self._factors[id(action)]
            if found is None:
                log.not_adjusted[self._index[id(action)]].append(item.name)
                continue
            figure = found.apply(figure, item.name)
            log.adjusted[self._index[id(action)]].append(item.name)
        return figure

    def period_notes(self, period: FiscalPeriod) -> list[Adjustment]:
        log = self._logs.get(period)
        if log is None:
            return []
        notes: list[Adjustment] = []
        label = _label(period)
        if log.adjusted:
            clauses = []
            for index in sorted(log.adjusted):
                found = self._factors[id(self.confirmed[index])]
                assert found is not None
                clauses.append(_clause(found, log.adjusted[index]))
            notes.append(
                Adjustment(
                    kind=AdjustmentKind.SHARE_BASIS,
                    period=period,
                    detail=(
                        f"{label}: {'; then '.join(clauses)}. Figures are on the share basis "
                        f"of {_day(self.day)}."
                    ),
                )
            )
        for index in sorted(log.not_adjusted):
            action = self.confirmed[index]
            notes.append(
                Adjustment(
                    kind=AdjustmentKind.SHARE_BASIS_NOT_ADJUSTED,
                    period=period,
                    detail=(
                        f"{label}: {_lines(log.not_adjusted[index])} not adjusted for the "
                        f"{describe(action)}: its factor cannot be derived yet, because the "
                        f"company prints none here and no cum-rights close is held. Left as "
                        f"filed, so these are not comparable with later periods."
                    ),
                )
            )
        for index in sorted(log.window):
            action = self.confirmed[index]
            notes.append(
                Adjustment(
                    kind=AdjustmentKind.SHARE_BASIS_WINDOW,
                    period=period,
                    detail=(
                        f"{label}: the {describe(action)} took effect after the period ended "
                        f"({_day(period.end)}) and before the report was filed. Per-share "
                        f"lines and weighted counts are taken as already on the new basis "
                        f"(IAS 33.64), the year-end count as not. Check the page for "
                        f"{_lines(log.window[index])}; set share_basis_date where it differs."
                    ),
                )
            )
        return notes

    def company_notes(self, series_start: date | None) -> list[Adjustment]:
        """Once per company: several live share classes, and spin-offs within the series."""
        notes: list[Adjustment] = []
        if self.multi_class:
            notes.append(
                Adjustment(
                    kind=AdjustmentKind.MULTIPLE_SHARE_CLASSES,
                    detail=(
                        f"{self.company.name} has {len(self.live)} share classes on "
                        f"{_day(self.day)} ({', '.join(self.live)}). Its per-share figures and "
                        f"share counts are left as filed and are not made comparable: a share "
                        f"of one class is not a share of another."
                    ),
                )
            )
        if series_start is None:
            return notes
        for action in self.confirmed:
            if action.kind is ActionKind.SPIN_OFF and series_start < action.ex_date <= self.day:
                notes.append(
                    Adjustment(
                        kind=AdjustmentKind.SPIN_OFF,
                        detail=(
                            f"The {describe(action)} is recorded and nothing is adjusted for "
                            f"it: a spin-off moves value out of the company, not the share "
                            f"basis. Figures before and after it describe different businesses."
                        ),
                    )
                )
        return notes


# --- Words ---

_KIND_WORDS = {
    ActionKind.SPLIT: "split",
    ActionKind.REVERSE_SPLIT: "reverse split",
    ActionKind.BONUS_ISSUE: "bonus issue",
    ActionKind.RIGHTS_ISSUE: "rights issue",
    ActionKind.SPIN_OFF: "spin-off",
}

_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def describe(action: CorporateAction) -> str:
    """``1:2 split of 2 June 2025 (Acme Annual Report 2025, p. 88)``: old shares to new."""
    if action.kind is ActionKind.CLASS_UNIFICATION:
        what = (
            f"unification of the {action.share_class} shares into {action.into_class} shares "
            f"({action.old_shares}:{action.new_shares})"
        )
    else:
        what = _KIND_WORDS.get(action.kind, action.kind.value.replace("_", " "))
        if action.new_shares is not None and action.old_shares is not None:
            what = f"{action.old_shares}:{action.new_shares} {what}"
    text = f"{what} of {_day(action.ex_date)}"
    if action.document is not None:
        page = f", p. {action.document.page}" if action.document.page is not None else ""
        text += f" ({action.document.document}{page})"
    return text


def _document(action: CorporateAction) -> str:
    doc = action.document
    if doc is None:
        return action.source
    parts = [doc.document]
    if doc.page is not None:
        parts.append(f"p. {doc.page}")
    if doc.pdf_page is not None:
        parts.append(f"PDF p. {doc.pdf_page}")
    parts.append(f"sha256 {doc.sha256[:12]}")
    return ", ".join(parts)


def _clause(found: Factor, lines: Sequence[LineItemName]) -> str:
    per_share = [n for n in lines if n in PER_SHARE_LINES]
    counts = [n for n in lines if n in COUNT_LINES]
    parts = []
    if per_share:
        parts.append(f"{_count(len(per_share), 'per-share line')} divided by {found.display}")
    if counts:
        parts.append(f"{_count(len(counts), 'share count')} multiplied by {found.display}")
    return f"{' and '.join(parts)}, for the {describe(found.action)}"


def _count(n: int, noun: str) -> str:
    word = _NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else str(n)
    return f"{word} {noun}{'' if n == 1 else 's'}"


def _lines(names: Sequence[LineItemName]) -> str:
    return ", ".join(n.value for n in names)


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _label(period: FiscalPeriod) -> str:
    if period.kind is PeriodKind.ANNUAL:
        return f"FY{period.fiscal_year}"
    return f"{period.kind.value.replace('_', '-')} to {period.end.isoformat()}"


def _exact_quotient(new: Decimal, old: Decimal) -> Decimal | None:
    """``new / old`` if a decimal holds it exactly (5, 0.1, 2.5), else None (2/3)."""
    with localcontext() as context:
        context.traps[Inexact] = True
        try:
            return new / old
        except Inexact:
            return None


def _ratio(node: Traced) -> Decimal:
    assert isinstance(node.value, Decimal)
    return node.value


def _plain(number: Decimal) -> str:
    normalized = number.normalize()
    return format(normalized, "f")
