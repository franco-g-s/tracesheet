"""What the multiples stage produces: one closing price set against the latest fiscal year.

Types only. The multiples are computed by ``tracesheet.multiples.compute_multiples``.
"""

from collections.abc import Mapping
from datetime import date

from tracesheet.model.base import Model
from tracesheet.model.metrics import MetricValue
from tracesheet.model.traced import Traced


class Multiples(Model):
    """Price multiples for one close: P/E, EV/EBIT, EV/EBITDA, FCF yield, P/B and dividend
    yield, keyed as in ``tracesheet.multiples.MULTIPLE_KEYS``.

    ``price`` is the close as observed, in its own currency, and its source names where it
    was read. When that currency differs from the reporting currency, ``exchange_rate`` is
    the rate every figure was converted at; otherwise it is ``None``. Market capitalisation
    and enterprise value are in the reporting currency, and either may be "n/m" with the
    reason, for instance when shares outstanding are not filed.
    """

    price: Traced
    """An observed per-share leaf."""
    price_date: date
    fiscal_year: int
    """The fiscal year the multiples are set against: the latest annual period."""
    exchange_rate: Traced | None = None
    market_cap: MetricValue
    enterprise_value: MetricValue
    values: Mapping[str, MetricValue]
