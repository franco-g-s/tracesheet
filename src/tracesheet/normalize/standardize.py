"""Standardization: fill the lines a report did not print from the ones it did.

For each relationship in ``tracesheet.model.relationships`` with exactly one member missing, the
missing member is solved from the others; the pass repeats until nothing more can be solved,
so a line calculated in one step can complete another. A printed figure is never replaced,
and two missing members of one relationship leave both missing. Each calculation is a traced
operation over printed figures, stored under ``PeriodFigures.calculated`` and stated in one
adjustment per period.
"""

from collections.abc import Mapping

from tracesheet.model import (
    DERIVED_ONLY,
    RELATIONSHIPS,
    Adjustment,
    AdjustmentKind,
    LineItemName,
    PeriodFigures,
    Relationship,
    Traced,
)
from tracesheet.model.traced import total


def standardize(block: PeriodFigures, label: str) -> tuple[PeriodFigures, Adjustment | None]:
    """The block with every line the relationships can solve for; the adjustment that says
    which, or None when nothing was calculated. ``label`` names the period in the sentence."""
    known: dict[LineItemName, Traced] = dict(block.figures)
    calculated: dict[LineItemName, Traced] = {}
    sentences: list[str] = []
    progress = True
    while progress:
        progress = False
        for relationship in RELATIONSHIPS:
            if not relationship.derive:
                continue
            solved = _solve(relationship, known)
            if solved is None:
                continue
            name, figure, sentence = solved
            known[name] = figure
            calculated[name] = figure
            sentences.append(sentence)
            progress = True
    if not calculated:
        return block, None
    note = Adjustment(
        kind=AdjustmentKind.CALCULATED,
        period=block.period,
        detail=f"{label}: " + "; ".join(sentences),
    )
    return block.model_copy(update={"calculated": calculated}), note


def _solve(
    relationship: Relationship, known: Mapping[LineItemName, Traced]
) -> tuple[LineItemName, Traced, str] | None:
    missing = [name for name in relationship.members if name not in known]
    if relationship.total in missing and relationship.absent_means_none:
        return _sum_of_printed_parts(relationship, known)
    if len(missing) != 1:
        return None
    unknown = missing[0]
    if unknown == relationship.total:
        figure = _plus(relationship.add, known)
        for name in relationship.subtract:
            figure = figure - known[name]
        return unknown, figure, f"{unknown} calculated as {_right(relationship)}"
    if unknown in relationship.add:
        # a part added into the total: total - the other added parts + the subtracted ones
        figure = known[relationship.total]
        others = [n for n in relationship.add if n != unknown]
        for name in others:
            figure = figure - known[name]
        for name in relationship.subtract:
            figure = figure + known[name]
        text = str(relationship.total) + "".join(f" - {n}" for n in others)
        text += "".join(f" + {n}" for n in relationship.subtract)
        if unknown in DERIVED_ONLY:
            # A section's remainder: its formula names every line of the section, which says
            # less than what it is. The trail behind the figure keeps the whole formula.
            text = f"the rest of {relationship.total}"
        return unknown, figure, f"{unknown} calculated as {text}"
    # a part subtracted to reach the total: the added parts - the total - the other subtracted
    others = [n for n in relationship.subtract if n != unknown]
    figure = _plus(relationship.add, known) - known[relationship.total]
    for name in others:
        figure = figure - known[name]
    text = " + ".join(relationship.add) + f" - {relationship.total}"
    text += "".join(f" - {n}" for n in others)
    return unknown, figure, f"{unknown} calculated as {text}"


def _sum_of_printed_parts(
    relationship: Relationship, known: Mapping[LineItemName, Traced]
) -> tuple[LineItemName, Traced, str] | None:
    """A plain sum whose unprinted parts mean none: the total from the parts printed."""
    printed = [name for name in relationship.add if name in known]
    if not printed:
        return None
    absent = [name for name in relationship.add if name not in known]
    sentence = f"{relationship.total} calculated as {' + '.join(printed)}"
    if absent:
        sentence += f" ({', '.join(absent)} not printed, taken as none)"
    return relationship.total, _plus(tuple(printed), known), sentence


def _plus(names: tuple[LineItemName, ...], known: Mapping[LineItemName, Traced]) -> Traced:
    figures = [known[name] for name in names]
    return figures[0] if len(figures) == 1 else total(*figures)


def _right(relationship: Relationship) -> str:
    return " + ".join(relationship.add) + "".join(f" - {n}" for n in relationship.subtract)
