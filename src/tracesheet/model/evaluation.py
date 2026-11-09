"""One evaluation: everything the pipeline produced for one company on one date.

An evaluation is a record, not a cache. It is built once by ``tracesheet.evaluate``, stored
once by ``tracesheet.storage``, and never changed afterwards: running the same company again
makes a new evaluation beside the old one.
"""

from collections.abc import Mapping

from pydantic import AwareDatetime, model_validator

from tracesheet.model.base import Model
from tracesheet.model.company import Company
from tracesheet.model.metrics import Metrics
from tracesheet.model.multiples import Multiples
from tracesheet.model.normalized import Normalized

SCHEMA_VERSION = 1
"""The shape of a stored evaluation. Storage refuses to read any other."""


class Evaluation(Model):
    """A company's figures, measures and multiples as of one date, with how they were made."""

    schema_version: int = SCHEMA_VERSION
    company: Company
    as_of: AwareDatetime
    """What the evaluation knows: nothing filed after this moment is in it."""
    created_at: AwareDatetime
    """When the evaluation was run. Later than ``as_of`` when a past date is evaluated."""
    normalized: Normalized
    metrics: Metrics
    multiples: Multiples | None
    """``None`` when no closing price was given."""
    tie_out: Mapping[str, tuple[str, ...]]
    """Every filing the figures were drawn from, by record id, with the accounting
    identities it fails. An empty tuple means the filing ties out."""
    code_version: str
    """The package version that produced it, with the commit when it ran from a checkout."""

    @model_validator(mode="after")
    def _one_company_one_date(self) -> "Evaluation":
        if self.normalized.company_id != self.company.id:
            msg = (
                f"the figures are for {self.normalized.company_id!r}, "
                f"the evaluation for {self.company.id!r}"
            )
            raise ValueError(msg)
        if self.normalized.as_of != self.as_of:
            msg = (
                f"the figures know what was filed by {self.normalized.as_of.isoformat()}, "
                f"the evaluation says {self.as_of.isoformat()}"
            )
            raise ValueError(msg)
        return self
