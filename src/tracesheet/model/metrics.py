"""What the metrics stage produces: one value per measure per year, and compound growth.

Types only. The measures are defined in ``tracesheet.metrics.catalogue`` and computed by
``tracesheet.metrics.compute_metrics``.
"""

from collections.abc import Mapping

from tracesheet.model.base import Model
from tracesheet.model.traced import Traced


class NotMeaningful(Model):
    """A measure that has no meaningful value this year, and why — shown as "n/m".

    The reason names what is missing or what made the arithmetic undefined, such as
    "profit before tax is zero or negative" or "gross profit not filed". Nothing is ever
    clamped or imputed in its place.
    """

    reason: str


MetricValue = Traced | NotMeaningful
"""A measure's value: a traced number, or the reason there is none."""


class YearMetrics(Model):
    """Every catalogue measure for one fiscal year, keyed by ``MetricDef.key``."""

    fiscal_year: int
    values: Mapping[str, MetricValue]


class Metrics(Model):
    """The measures for every year, oldest first, and compound annual growth rates.

    ``cagr`` maps a measure's key to its growth over a number of years ending in the latest
    year: ``cagr["revenue"][5]`` is the five-year compound annual growth of revenue.
    """

    years: tuple[YearMetrics, ...]
    cagr: Mapping[str, Mapping[int, MetricValue]]
