"""The metrics documentation is generated from the catalogue, so it cannot drift from it."""

from pathlib import Path

from tracesheet.metrics import CATALOGUE, CONVENTIONS
from tracesheet.metrics.docs import metrics_markdown

METRICS_MD = Path(__file__).parents[1] / "docs" / "METRICS.md"


def test_metrics_md_is_the_generators_output() -> None:
    # Regenerate with: uv run python -m tracesheet.metrics.docs > docs/METRICS.md
    assert METRICS_MD.read_text(encoding="utf-8") == metrics_markdown()


def test_every_measure_and_convention_is_documented() -> None:
    text = metrics_markdown()
    for metric in CATALOGUE:
        assert f"| {metric.label} |" in text
        assert metric.formula in text
    for topic, convention in CONVENTIONS:
        assert f"| {topic} | {convention} |" in text


def test_ends_in_exactly_one_newline() -> None:
    text = metrics_markdown()
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
