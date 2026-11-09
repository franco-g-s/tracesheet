"""The runner: one company's typed-in files in, one complete evaluation out.

The stages run in a fixed order — load, normalize, metrics, multiples — and each one only
reads what the previous one produced. The runner adds nothing of its own beyond the tie-out
of every filing used and a note of which code did the work.
"""

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from tracesheet import __version__
from tracesheet.metrics import compute_metrics
from tracesheet.model import CompanyId, Evaluation, PriceObservation, Traced
from tracesheet.multiples import compute_multiples
from tracesheet.normalize import normalize
from tracesheet.providers import HandLoaded, reconcile

_PACKAGE = Path(__file__).resolve().parent


def evaluate(  # noqa: PLR0913 - the price, its rate and the clock are each a separate input
    root: Path,
    company_id: CompanyId,
    as_of: datetime,
    price: PriceObservation | None,
    rate: Traced | None = None,
    *,
    created_at: datetime | None = None,
) -> Evaluation:
    """Evaluate one company as of one moment, from the typed-in files under ``root``.

    ``as_of`` is what the evaluation may know: a filing published after it is left out, so a
    past date can be evaluated without hindsight. ``price`` is the close the multiples are
    set against; without one there are no multiples. ``rate`` converts that close into the
    reporting currency when the two differ. ``created_at`` is when the run happened; it
    defaults to now, in UTC.
    """
    provider = HandLoaded(root)
    company = provider.company(company_id)
    records = provider.financial_records(company_id)
    normalized = normalize(
        company,
        records,
        as_of,
        actions=provider.actions(company_id),
        prices=() if price is None else (price,),
    )
    metrics = compute_metrics(normalized)
    multiples = compute_multiples(normalized, metrics, price, rate)
    by_id = {record.id: record for record in records}
    tie_out: dict[str, tuple[str, ...]] = {
        ref.id: reconcile(by_id[ref.id], provider.tolerance(company_id, ref.id))
        for ref in normalized.used
    }
    return Evaluation(
        company=company,
        as_of=as_of,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        normalized=normalized,
        metrics=metrics,
        multiples=multiples,
        tie_out=tie_out,
        code_version=code_version(),
    )


def code_version() -> str:
    """The package version, plus ``+<short commit>`` when it runs from its own git checkout.

    Never fails: without git, outside a checkout, or inside someone else's repository (an
    install in a virtual environment there), it is the version alone.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD", "--show-toplevel"],
            cwd=_PACKAGE,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return __version__
    # Git prints the top level and the commit in an order of its own; tell them apart by
    # shape rather than by line order.
    paths = [line for line in result.stdout.splitlines() if Path(line).is_absolute()]
    commits = [line for line in result.stdout.splitlines() if re.fullmatch(r"[0-9a-f]{4,40}", line)]
    if len(paths) != 1 or len(commits) != 1:
        return __version__
    if Path(paths[0]).resolve() / "src" / "tracesheet" != _PACKAGE:
        return __version__
    return f"{__version__}+{commits[0]}"
