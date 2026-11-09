"""The metrics documentation, generated from the catalogue so it cannot drift from the code.

``docs/METRICS.md`` is exactly what ``metrics_markdown`` returns, and a test holds it to
that. After changing a measure, a multiple or a convention, regenerate it::

    uv run python -m tracesheet.metrics.docs > docs/METRICS.md

The tables follow the sheet: the same sections in the same order, then compound growth, the
valuation multiples and the conventions the measures share.
"""

import sys

from tracesheet.metrics.catalogue import CAGR_KEYS, CAGR_SPANS, CATALOGUE, CONVENTIONS
from tracesheet.multiples import MULTIPLE_KEYS
from tracesheet.report.build import GROUP_TITLES, MULTIPLE_DEFS, SECTIONS

_INTRO = (
    "# Metrics",
    "",
    "Every measure on the sheet, with the formula it is computed by, and the conventions the",
    "measures share. The sheet describes and does not judge: no measure has a threshold, a",
    "target or a notion of a good or bad value. A value that cannot be computed is shown as",
    "n/m with the reason.",
    "",
    "This file is generated from `src/tracesheet/metrics/catalogue.py`. Do not edit it by",
    "hand; regenerate it with `uv run python -m tracesheet.metrics.docs > docs/METRICS.md`.",
)


def metrics_markdown() -> str:
    """The full text of ``docs/METRICS.md``, ending in a single newline."""
    labels = {m.key: m.label for m in CATALOGUE}
    lines = list(_INTRO)

    for title, sections in SECTIONS:
        lines += ["", f"## {title}"]
        for section in sections:
            group = GROUP_TITLES.get(section)
            if group is not None:
                lines += ["", f"### {group}"]
            lines += ["", "| Measure | Formula |", "| --- | --- |"]
            lines += [
                f"| {_cell(m.label)} | {_cell(m.formula)} |"
                for m in CATALOGUE
                if m.section is section
            ]

    spans = " and ".join(str(span) for span in CAGR_SPANS)
    lines += [
        "",
        "## Compound annual growth",
        "",
        f"Over n = {spans} fiscal years, ending in the latest year: (latest year's value ÷ the",
        "value n years earlier)^(1 ÷ n) − 1. Undefined when either value is zero or negative,",
        "or when the earlier year has no figures.",
        "",
        "Computed for: " + ", ".join(labels[key] for key in CAGR_KEYS) + ".",
    ]

    lines += [
        "",
        "## Valuation multiples",
        "",
        "Set from one closing price against the latest fiscal year. Each states the price, its",
        "date and its source. Without a price the section says so, and the rest of the sheet",
        "still renders.",
        "",
        "| Multiple | Formula |",
        "| --- | --- |",
    ]
    for key in MULTIPLE_KEYS:
        label, _, formula = MULTIPLE_DEFS[key]
        lines.append(f"| {_cell(label)} | {_cell(formula)} |")

    lines += ["", "## Conventions", "", "| Topic | Convention |", "| --- | --- |"]
    lines += [f"| {_cell(topic)} | {_cell(text)} |" for topic, text in CONVENTIONS]
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    """Text made safe for one cell of a Markdown table."""
    return text.replace("|", "\\|")


if __name__ == "__main__":
    sys.stdout.write(metrics_markdown())
