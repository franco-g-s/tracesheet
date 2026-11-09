"""The normalization stage. ``normalize`` is the only way to get a ``Normalized``: filed
figures in, comparable figures out."""

from tracesheet.normalize.rates import YearRates, find_rates
from tracesheet.normalize.stage import NormalizationError, normalize
from tracesheet.normalize.standardize import standardize

__all__ = [
    "NormalizationError",
    "YearRates",
    "find_rates",
    "normalize",
    "standardize",
]
