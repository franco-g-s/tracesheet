"""The market cache: vendor observations under ``data/cache/market/``, gitignored.

One JSON-lines file per company and kind, decimals as text, one observation per line,
keyed by day. Appending a day already present with identical content is a no-op; with
different content it is refused, because a close does not change after the fact and a
vendor that says otherwise is a fact worth a human's look.
"""

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TypeVar

from tracesheet.model import CompanyId, CorporateAction, Model, PriceObservation, SharesObservation

PRICES = "prices.jsonl"
ACTIONS = "actions.jsonl"
SHARES = "shares.jsonl"

M = TypeVar("M", PriceObservation, CorporateAction, SharesObservation)


class CacheError(ValueError):
    """The cache holds a different observation for the same day."""


class MarketCache:
    """Vendor observations kept on disk, so a fetched day need not be fetched again."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- prices ---

    def append_prices(self, observations: Iterable[PriceObservation]) -> int:
        """Append new days; return how many were new."""
        return self._append(
            PRICES, observations, PriceObservation, key=lambda o: o.date.isoformat()
        )

    def prices(self, company: CompanyId) -> tuple[PriceObservation, ...]:
        rows = self._read(company, PRICES, PriceObservation)
        return tuple(sorted(rows, key=lambda o: o.date))

    # --- corporate actions and shares ---

    def append_actions(self, actions: Iterable[CorporateAction]) -> int:
        return self._append(
            ACTIONS,
            actions,
            CorporateAction,
            key=lambda a: f"{a.ex_date.isoformat()}:{a.kind.value}",
        )

    def actions(self, company: CompanyId) -> tuple[CorporateAction, ...]:
        rows = self._read(company, ACTIONS, CorporateAction)
        return tuple(sorted(rows, key=lambda a: a.ex_date))

    def append_shares(self, observations: Iterable[SharesObservation]) -> int:
        return self._append(
            SHARES,
            observations,
            SharesObservation,
            key=lambda s: f"{s.date.isoformat()}:{s.kind.value}",
        )

    def shares(self, company: CompanyId) -> tuple[SharesObservation, ...]:
        rows = self._read(company, SHARES, SharesObservation)
        return tuple(sorted(rows, key=lambda s: s.date))

    # --- internals ---

    def _append(
        self,
        file: str,
        items: Iterable[M],
        model: type[M],
        *,
        key: Callable[[M], str],
    ) -> int:
        new = 0
        by_company: dict[str, list[M]] = {}
        for item in items:
            by_company.setdefault(str(item.company_id), []).append(item)
        for company, rows in by_company.items():
            existing = {key(r): r for r in self._read(CompanyId(company), file, model)}
            path = self.root / company / file
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as out:
                for row in rows:
                    k = key(row)
                    if k in existing:
                        if _content(existing[k]) != _content(row):
                            msg = f"{path}: {k} is already cached with different content"
                            raise CacheError(msg)
                        continue
                    out.write(row.model_dump_json() + "\n")
                    existing[k] = row
                    new += 1
        return new

    def _read(self, company: CompanyId, file: str, model: type[M]) -> Sequence[M]:
        path = self.root / company / file
        if not path.is_file():
            return ()
        return [
            model.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _content(item: Model) -> str:
    """The observation without the moment it was fetched, for comparing two fetches."""
    data = item.model_dump(mode="json")
    data.pop("retrieved_at", None)
    return json.dumps(data, sort_keys=True)
