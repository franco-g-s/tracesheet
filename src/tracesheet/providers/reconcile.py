"""The identities a set of filed figures must satisfy: what an accountant calls "tying out".

Accounting arithmetic only: total assets equal total liabilities plus equity, a subtotal is
the sum of its parts, a part never exceeds its whole, and printed earnings per share follow
from earnings and the share count. The sums come from ``tracesheet.model.relationships``,
the same table normalization solves to fill a missing line; only the inequalities and the
per-share check live here. A typo in a total breaks one of these, and load time is the
cheapest moment to find it.
"""

from decimal import Decimal

from tracesheet.model import FinancialRecord, LineItemName, Money, ShareCount
from tracesheet.model.relationships import RELATIONSHIPS

_PART_OF: tuple[tuple[LineItemName, LineItemName], ...] = (
    (LineItemName.CURRENT_ASSETS, LineItemName.TOTAL_ASSETS),
    (LineItemName.INTANGIBLE_ASSETS, LineItemName.TOTAL_ASSETS),
    (LineItemName.CASH_AND_EQUIVALENTS, LineItemName.TOTAL_ASSETS),
    (LineItemName.CASH_AND_EQUIVALENTS, LineItemName.CURRENT_ASSETS),
    (LineItemName.CURRENT_LIABILITIES, LineItemName.TOTAL_LIABILITIES),
    (LineItemName.GROSS_PROFIT, LineItemName.REVENUE),
    (LineItemName.GOODWILL, LineItemName.INTANGIBLE_ASSETS),
    (LineItemName.OTHER_INTANGIBLE_ASSETS, LineItemName.INTANGIBLE_ASSETS),
    (LineItemName.CURRENT_LEASE_LIABILITIES, LineItemName.CURRENT_LIABILITIES),
    (LineItemName.CURRENT_BORROWINGS, LineItemName.CURRENT_LIABILITIES),
    (LineItemName.INVENTORIES, LineItemName.CURRENT_ASSETS),
    (LineItemName.TRADE_RECEIVABLES, LineItemName.CURRENT_ASSETS),
    (LineItemName.LEASE_LIABILITIES, LineItemName.TOTAL_LIABILITIES),
    (LineItemName.NON_CONTROLLING_INTERESTS, LineItemName.TOTAL_EQUITY),
)

_PER_SHARE: tuple[tuple[LineItemName, LineItemName], ...] = (
    # a printed earnings per share, and the share count the report divides it by
    (LineItemName.EPS_DILUTED, LineItemName.SHARES_DILUTED),
    (LineItemName.EPS_BASIC, LineItemName.SHARES_BASIC),
)


def _amount(record: FinancialRecord, name: LineItemName) -> Money | None:
    value = record.get(name)
    return value if isinstance(value, Money) else None


def reconcile(record: FinancialRecord, tolerance: Money) -> tuple[str, ...]:
    """Return one sentence per identity that fails; an empty tuple means the figures tie.

    ``tolerance`` is how far apart two figures may be and still count as equal. The loader
    passes one unit of the scale the report prints in, because each printed line is rounded
    separately; a smaller tolerance asks for a closer match.
    """
    failures: list[str] = []
    for relationship in RELATIONSHIPS:
        total_name, plus, minus = relationship.total, relationship.add, relationship.subtract
        total_value = _amount(record, total_name)
        added = [_amount(record, name) for name in plus]
        subtracted = [_amount(record, name) for name in minus]
        if total_value is None or None in added or None in subtracted:
            continue
        expected = Money(amount=Decimal(0), currency=total_value.currency)
        for part in added:
            assert part is not None
            expected = expected + part
        for part in subtracted:
            assert part is not None
            expected = expected - part
        difference = total_value - expected
        if abs(difference.amount) > tolerance.amount:
            formula = " + ".join(plus) + "".join(f" - {name}" for name in minus)
            failures.append(
                f"{total_name} {total_value} does not equal {formula} {expected} "
                f"(difference {difference})"
            )
    failures.extend(_per_share_failures(record, tolerance))
    for part_name, whole_name in _PART_OF:
        part = _amount(record, part_name)
        whole = _amount(record, whole_name)
        if part is not None and whole is not None and part.amount > whole.amount + tolerance.amount:
            failures.append(f"{part_name} {part} exceeds {whole_name} {whole}")
    return tuple(failures)


def _per_share_failures(record: FinancialRecord, tolerance: Money) -> list[str]:
    """Earnings attributable to owners, divided by the share count, must reproduce the
    printed earnings per share.

    Allowed: half a unit of the last printed digit of the EPS (0.005 for a figure to the
    cent) plus the rounding of the printed earnings (half of ``tolerance``) spread over the
    shares. A count typed in the wrong scale, or taken from the wrong column, misses by
    orders of magnitude.
    """
    owners = _amount(record, LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS)
    failures: list[str] = []
    for eps_name, shares_name in _PER_SHARE:
        eps = _amount(record, eps_name)
        shares = record.get(shares_name)
        if owners is None or eps is None or not isinstance(shares, ShareCount):
            continue
        if shares.count <= 0:
            failures.append(f"{shares_name} {shares} is not a positive count")
            continue
        exponent = eps.amount.as_tuple().exponent
        step = Decimal(1).scaleb(exponent if isinstance(exponent, int) else 0)
        allowed = step / 2 + (tolerance.amount / 2) / shares.count
        implied = owners.amount / shares.count
        if abs(implied - eps.amount) > allowed:
            failures.append(
                f"{eps_name} {eps} is not {LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS} / "
                f"{shares_name} = {implied:.4f} (allowed {allowed:.4f})"
            )
    return failures
