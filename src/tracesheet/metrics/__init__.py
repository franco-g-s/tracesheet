"""The metrics stage: a textbook catalogue of measures, computed for every year with its
trail. ``compute_metrics`` turns normalized figures into ``Metrics``."""

from tracesheet.metrics.catalogue import (
    CAGR_KEYS,
    CAGR_SPANS,
    CATALOGUE,
    CONVENTIONS,
    Kind,
    MetricDef,
    Section,
)
from tracesheet.metrics.stage import compute_metrics

__all__ = [
    "CAGR_KEYS",
    "CAGR_SPANS",
    "CATALOGUE",
    "CONVENTIONS",
    "Kind",
    "MetricDef",
    "Section",
    "compute_metrics",
]
