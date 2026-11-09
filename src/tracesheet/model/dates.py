"""Periods and year ends.

Events (a filing, an evaluation, a price observation) are timezone-aware datetimes,
declared on each object with pydantic's ``AwareDatetime``. Periods are bounded by plain
dates, because a report covers whole days.
"""

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from tracesheet.model.base import Model


class PeriodKind(StrEnum):
    """How long a reporting period is."""

    ANNUAL = "annual"
    HALF_YEAR = "half_year"
    QUARTER = "quarter"


class FiscalPeriod(Model):
    """One reporting period with explicit bounds. A fiscal year need not be a calendar year."""

    start: date
    end: date
    kind: PeriodKind

    @model_validator(mode="after")
    def _end_after_start(self) -> "FiscalPeriod":
        if self.end < self.start:
            msg = f"period end {self.end} precedes its start {self.start}"
            raise ValueError(msg)
        return self

    @property
    def fiscal_year(self) -> int:
        """The year the period ends in — how companies label a fiscal year."""
        return self.end.year


class MonthDay(Model):
    """A recurring day of the year, such as a company's fiscal year end."""

    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)

    @model_validator(mode="after")
    def _exists_in_some_year(self) -> "MonthDay":
        # 2000 is a leap year, so 29 February is allowed and 31 April is not.
        date(2000, self.month, self.day)
        return self
