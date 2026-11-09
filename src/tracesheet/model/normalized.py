"""What the normalization stage produces: comparable figures, and a record of what it did.

Types only. The stage itself, ``normalize``, lives in ``tracesheet.normalize``.
"""

from collections.abc import Mapping
from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from tracesheet.model.base import Model, chain_runs_backwards
from tracesheet.model.dates import FiscalPeriod
from tracesheet.model.financial_record import LineItemName, RecordRef
from tracesheet.model.ids import CompanyId
from tracesheet.model.money import Currency
from tracesheet.model.traced import Filed, Traced


class AdjustmentKind(StrEnum):
    RESTATEMENT_USED = "restatement_used"
    MIXED_FILINGS = "mixed_filings"
    EXCLUDED_AFTER_AS_OF = "excluded_after_as_of"
    GAP = "gap"
    IRREGULAR_PERIOD = "irregular_period"
    YEAR_END_MISMATCH = "year_end_mismatch"
    CURRENCY_CONVERTED = "currency_converted"
    SHARE_BASIS = "share_basis"
    """Per-share figures and counts put on the share basis of ``as_of``."""
    SHARE_BASIS_WINDOW = "share_basis_window"
    """A share-basis action fell between a period's end and its filing: check the page."""
    SHARE_BASIS_NOT_ADJUSTED = "share_basis_not_adjusted"
    """An action whose factor cannot be derived yet, such as a rights issue without a
    printed factor or a price. Left as filed, and said so."""
    SPIN_OFF = "spin_off"
    """Recorded, never adjusted: a spin-off moves value out, not the share basis."""
    MULTIPLE_SHARE_CLASSES = "multiple_share_classes"
    """More than one live share class: per-share figures and counts not made comparable."""
    FINER_PRECISION_KEPT = "finer_precision_kept"
    """A later report re-printed a line unchanged or within its own rounding: the earlier
    figure was kept, and the later one corroborates it."""
    CALCULATED = "calculated"
    """A line the report did not print, solved from an accounting relationship between lines
    it did print."""


class Adjustment(Model):
    """One thing normalization did or noticed, in plain words. Part of the answer."""

    kind: AdjustmentKind
    detail: str
    period: FiscalPeriod | None = None


class PeriodFigures(Model):
    """One period's comparable figures, each a traced number naming its filing."""

    period: FiscalPeriod
    figures: Mapping[LineItemName, Traced]
    calculated: Mapping[LineItemName, Traced] = Field(default_factory=dict)
    """Lines the report did not print, solved from the accounting relationships between the
    lines it did. Never a line that is also in ``figures``: a printed figure is never
    replaced."""
    irregular: bool = False
    """An annual period that is not about twelve months long. Kept, and marked as such."""

    @model_validator(mode="after")
    def _printed_wins(self) -> "PeriodFigures":
        both = sorted(set(self.figures) & set(self.calculated))
        if both:
            msg = f"a printed line is never also calculated: {', '.join(both)}"
            raise ValueError(msg)
        return self

    @property
    def fiscal_year(self) -> int:
        return self.period.fiscal_year

    def line(self, name: LineItemName) -> Traced | None:
        """The line as printed, or as calculated when the report did not print it. Every
        reader of a year goes through here."""
        printed = self.figures.get(name)
        return printed if printed is not None else self.calculated.get(name)

    def is_calculated(self, name: LineItemName) -> bool:
        return name not in self.figures and name in self.calculated


class Normalized(Model):
    company_id: CompanyId
    as_of: AwareDatetime
    """What the figures know: nothing filed after this date is in them."""
    currency: Currency
    years: tuple[PeriodFigures, ...]
    """The annual series, oldest first. The backbone of every long-run measure."""
    interim: tuple[PeriodFigures, ...] = ()
    """Half-year and quarterly filings, oldest first. The latest picture, not the record."""
    used: tuple[RecordRef, ...]
    """Every filing that contributed a figure."""
    adjustments: tuple[Adjustment, ...] = ()

    @model_validator(mode="after")
    def _ordered_and_knowable(self) -> "Normalized":
        ends = [p.period.end for p in self.years]
        if ends != sorted(ends) or len({p.fiscal_year for p in self.years}) != len(self.years):
            msg = "the annual series must be oldest first with one entry per fiscal year"
            raise ValueError(msg)
        interim_ends = [p.period.end for p in self.interim]
        if interim_ends != sorted(interim_ends):
            msg = "the interim series must be oldest first"
            raise ValueError(msg)
        for block in (*self.years, *self.interim):
            for figure in (*block.figures.values(), *block.calculated.values()):
                for origin in figure.sources():
                    if isinstance(origin, Filed) and origin.record.filed_at > self.as_of:
                        raise chain_runs_backwards(
                            f"a figure for {block.period.end} comes from {origin.record.id}, "
                            f"filed {origin.record.filed_at.isoformat()}, after as_of "
                            f"{self.as_of.isoformat()}; that is look-ahead bias"
                        )
        return self

    # --- Reading the series ---

    @property
    def fiscal_years(self) -> tuple[int, ...]:
        return tuple(p.fiscal_year for p in self.years)

    @property
    def gaps(self) -> tuple[int, ...]:
        """Fiscal years missing between the first and the last. Reported, never filled."""
        if not self.years:
            return ()
        present = set(self.fiscal_years)
        return tuple(y for y in range(min(present), max(present) + 1) if y not in present)

    def year(self, fiscal_year: int) -> PeriodFigures:
        for block in self.years:
            if block.fiscal_year == fiscal_year:
                return block
        raise KeyError(fiscal_year)

    def latest_year_ending_by(self, cutoff: date) -> PeriodFigures | None:
        """The most recent complete fiscal year ending on or before ``cutoff``: the
        primitive for lining several companies up on the same date."""
        candidates = [p for p in self.years if p.period.end <= cutoff]
        return candidates[-1] if candidates else None
