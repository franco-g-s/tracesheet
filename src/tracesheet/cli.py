"""The command line: ``load`` a company's typed-in files, ``evaluate`` and store, or
``render`` the sheet without storing anything.

Exit codes: 0 on success; 1 when ``load`` finds a record that fails to tie out, or actions
or records that normalization refuses; 2 on a usage error or an unknown or malformed
company. Errors are one plain line, never a traceback.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Protocol

from tracesheet.evaluate import evaluate
from tracesheet.model import Company, CompanyId, Evaluation, FinancialRecord, PriceObservation
from tracesheet.normalize import NormalizationError, normalize
from tracesheet.providers import (
    FetchError,
    HandLoaded,
    HandLoadedError,
    reconcile,
    urllib_fetch,
)
from tracesheet.providers.documents import DocumentsError, documents_by_hash
from tracesheet.providers.market import TOKEN_VARIABLE, Eodhd, LocalPrices, LocalPricesError
from tracesheet.report import build_page, render
from tracesheet.storage import Store

EXIT_OK = 0
EXIT_TIE_OUT = 1
EXIT_USAGE = 2


class PriceSource(Protocol):
    """Anything that can name a company's latest close on or before a day."""

    def latest_close(self, company: Company, on_or_before: date) -> PriceObservation | None: ...


def choose_price(
    company: Company,
    as_of: date,
    local: PriceSource,
    feed: PriceSource | None = None,
) -> PriceObservation | None:
    """Pick the close a sheet is set against, and say on stderr where it came from.

    The market ``feed`` goes first when there is one. If it fails or has nothing, the
    ``local`` price file is tried, then no price at all. Missing network or token is never
    an error: the sheet is built without multiples and says so.
    """
    if feed is not None:
        try:
            found = feed.latest_close(company, as_of)
        except FetchError as error:
            _note(f"price: eodhd failed ({error}); falling back to the local price file")
        else:
            if found is not None:
                _note(f"price: eodhd close of {found.date}")
                return found
            _note("price: eodhd had no close; falling back to the local price file")
    found = local.latest_close(company, as_of)
    if found is None:
        _note("price: no price available; the sheet is built without multiples")
        return None
    _note(f"price: {found.source}, close of {found.date}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = _parser().parse_args(argv)
    try:
        return int(args.run(args))
    except (HandLoadedError, DocumentsError, LocalPricesError) as error:
        _note(f"tracesheet: {error}")
        return EXIT_USAGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracesheet", description="Traceable company evaluation sheets."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="read a company's files and check they tie out")
    _common(load)
    load.set_defaults(run=_load)

    for name, helptext, run in (
        ("evaluate", "evaluate, store the result and print its manifest id", _evaluate),
        ("render", "evaluate in memory and write the sheet as HTML", _render),
    ):
        command = commands.add_parser(name, help=helptext)
        _common(command)
        command.add_argument(
            "--as-of",
            type=_day,
            default=None,
            help="the day to evaluate as of, YYYY-MM-DD (default: today, UTC)",
        )
        command.add_argument("--prices", type=Path, default=Path("data/prices.toml"))
        command.add_argument("--no-price", action="store_true", help="build without a share price")
        if name == "evaluate":
            command.add_argument("--store", type=Path, default=Path("data/evaluations"))
        else:
            command.add_argument(
                "--out", type=Path, default=None, help="default: examples/<company>.html"
            )
        command.set_defaults(run=run)
    return parser


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument("company")
    command.add_argument("--root", type=Path, default=Path("data/companies"))


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        msg = f"{text!r} is not a date; write it as YYYY-MM-DD"
        raise argparse.ArgumentTypeError(msg) from None


def _known(args: argparse.Namespace) -> tuple[HandLoaded, CompanyId] | None:
    provider = HandLoaded(args.root)
    company = CompanyId(args.company)
    try:
        provider.company(company)
    except HandLoadedError as error:
        # A missing company and a malformed company.toml both land here; the error names
        # the file and what is wrong with it.
        _note(f"tracesheet: {error}")
        return None
    return provider, company


def _load(args: argparse.Namespace) -> int:
    known = _known(args)
    if known is None:
        return EXIT_USAGE
    provider, company = known
    try:
        records = provider.financial_records(company)
    except HandLoadedError as error:
        print(f"FAILS   {error}")
        return EXIT_TIE_OUT
    failed = False
    for record in records:
        failures = reconcile(record, provider.tolerance(company, record.id))
        if failures:
            failed = True
            print(f"FAILS   {record.id}: " + "; ".join(failures))
        else:
            print(f"{record.id}: ties out")
    if not _actions_apply(provider, company, records):
        failed = True
    return EXIT_TIE_OUT if failed else EXIT_OK


def _actions_apply(
    provider: HandLoaded, company: CompanyId, records: Sequence[FinancialRecord]
) -> bool:
    """Read the share-basis actions and normalize with them as of now, as ``evaluate``
    would, so that a broken action or a record normalization refuses shows up at load
    time. Prints one line either way and says whether it worked."""
    try:
        actions = provider.actions(company)
        normalize(provider.company(company), records, datetime.now(UTC), actions=actions)
    except HandLoadedError as error:
        print(f"FAILS   actions: {error}")
        return False
    except NormalizationError as error:
        print(f"FAILS   normalization: {error}")
        return False
    count = f"{len(actions)} action" + ("" if len(actions) == 1 else "s")
    print(f"actions.toml: {count}, confirmed and applied")
    return True


def _run_evaluation(args: argparse.Namespace) -> Evaluation | None:
    known = _known(args)
    if known is None:
        return None
    provider, company_id = known
    day: date = args.as_of or datetime.now(UTC).date()
    price = None
    if not args.no_price:
        company = provider.company(company_id)
        feed = _feed() if os.environ.get(TOKEN_VARIABLE) else None
        price = choose_price(company, day, LocalPrices(args.prices), feed)
    # The whole of the day counts as known: a filing published that day is included.
    as_of = datetime.combine(day, time.max, tzinfo=UTC).replace(microsecond=0)
    return evaluate(args.root, company_id, as_of, price)


def _feed() -> Eodhd | None:
    try:
        return Eodhd(urllib_fetch)
    except FetchError:
        return None


def _evaluate(args: argparse.Namespace) -> int:
    evaluation = _run_evaluation(args)
    if evaluation is None:
        return EXIT_USAGE
    print(Store(args.store).save(evaluation))
    return EXIT_OK


def _render(args: argparse.Namespace) -> int:
    evaluation = _run_evaluation(args)
    if evaluation is None:
        return EXIT_USAGE
    documents = documents_by_hash(args.root, evaluation.company.id)
    html = render(build_page(evaluation, documents))
    out: Path = args.out or Path("examples") / f"{args.company}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    _note(f"wrote {out}")
    return EXIT_OK


def _note(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
