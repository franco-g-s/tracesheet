"""The accounting relationships between statement lines, each written once.

Each relationship is an equation, ``total = sum(add) - sum(subtract)``, and is used twice:

- **as a check**, at load time: when every member is printed, they must tie to within the
  printed rounding, or the record is refused;
- **as a recipe**, in normalization: when exactly one member is missing, it is solved for
  from the others and stored, marked as calculated.

An equation solved for its one unknown can never loop, and one row serves every direction:
``EBITDA = EBIT + D&A`` gives EBITDA for a company that prints depreciation and depreciation
for a company that prints EBITDA. A row is only here if both sides mean the same thing under
``DEFINITION`` in ``tracesheet.model.financial_record``; that is what makes the recipe correct.
"""

from pydantic import model_validator

from tracesheet.model.base import Model
from tracesheet.model.financial_record import COUNT_LINES, PER_SHARE_LINES, LineItemName

L = LineItemName


class Relationship(Model):
    """One equation between statement lines: ``total = sum(add) - sum(subtract)``."""

    total: LineItemName
    add: tuple[LineItemName, ...]
    subtract: tuple[LineItemName, ...] = ()
    absent_means_none: bool = False
    """When solving for the total, a part the report does not print is taken as none, and
    the calculation says so. Never set on a sum a measure reads, such as debt or leases: there
    a part the company has none of must be declared not printed in the record, so that the
    zero is filed, with its page, rather than assumed."""
    derive: bool = True
    """False for a relationship that is a sound check but not a safe recipe."""
    note: str

    @model_validator(mode="after")
    def _well_formed(self) -> "Relationship":
        members = self.members
        if len(set(members)) != len(members):
            msg = f"{self.total}: a line appears twice in one relationship"
            raise ValueError(msg)
        if not self.add:
            msg = f"{self.total}: a relationship needs at least one line to add"
            raise ValueError(msg)
        shared = set(members) & (COUNT_LINES | PER_SHARE_LINES)
        if shared:
            msg = f"{self.total}: only amounts are related by sums, not {sorted(shared)}"
            raise ValueError(msg)
        if self.absent_means_none and self.subtract:
            msg = f"{self.total}: an absent part can mean none only in a plain sum"
            raise ValueError(msg)
        return self

    @property
    def members(self) -> tuple[LineItemName, ...]:
        return (self.total, *self.add, *self.subtract)

    def formula(self) -> str:
        """``ebitda = ebit + depreciation_amortization`` — for messages."""
        right = " + ".join(self.add) + "".join(f" - {name}" for name in self.subtract)
        return f"{self.total} = {right}"


RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship(
        total=L.TOTAL_ASSETS,
        add=(L.TOTAL_LIABILITIES, L.TOTAL_EQUITY),
        note="the balance sheet balances",
    ),
    Relationship(
        total=L.TOTAL_ASSETS,
        add=(L.TOTAL_LIABILITIES_AND_EQUITY,),
        note="the two sides of the balance sheet are equal",
    ),
    Relationship(
        total=L.TOTAL_LIABILITIES_AND_EQUITY,
        add=(L.TOTAL_LIABILITIES, L.TOTAL_EQUITY),
        note="liabilities and equity, the right-hand side of the balance sheet",
    ),
    Relationship(
        total=L.INTANGIBLE_ASSETS,
        add=(L.GOODWILL, L.OTHER_INTANGIBLE_ASSETS),
        absent_means_none=True,
        note="intangible assets are goodwill and the other intangibles",
    ),
    Relationship(
        total=L.LEASE_LIABILITIES,
        add=(L.NON_CURRENT_LEASE_LIABILITIES, L.CURRENT_LEASE_LIABILITIES),
        note="lease liabilities, long-term and short-term",
    ),
    Relationship(
        total=L.FINANCIAL_DEBT,
        add=(L.NON_CURRENT_BORROWINGS, L.CURRENT_BORROWINGS),
        note="borrowings, long-term and short-term, leases excluded",
    ),
    Relationship(
        total=L.GROSS_PROFIT,
        add=(L.REVENUE,),
        subtract=(L.COST_OF_SALES,),
        note="gross profit is revenue less cost of sales",
    ),
    Relationship(
        total=L.EBITDA,
        add=(L.EBIT, L.DEPRECIATION_AMORTIZATION),
        note="EBITDA is EBIT before depreciation, amortisation and impairment",
    ),
    Relationship(
        total=L.NET_INCOME,
        add=(L.PROFIT_BEFORE_TAX,),
        subtract=(L.INCOME_TAX_EXPENSE,),
        derive=False,
        note=(
            "net income is profit before tax less tax; a check only, because profit from "
            "discontinued operations can sit between them"
        ),
    ),
    Relationship(
        total=L.NET_INCOME,
        add=(L.NET_INCOME_ATTRIBUTABLE_TO_OWNERS, L.NET_INCOME_ATTRIBUTABLE_TO_MINORITIES),
        note="net income is the owners' share and the minorities' share",
    ),
    # The cash-flow statement. Outflows are held as positive magnitudes and
    # section totals are signed as printed, so an outflow is subtracted. The two "other"
    # lines are never typed: solving for them is what makes the sections tie by construction,
    # and it is only possible once every typed line of the section is present or declared
    # not printed.
    # Gross and net never share a line: each pair has a net line, solved from
    # the gross pair or typed where only the net is printed, and the sections read the net.
    Relationship(
        total=L.NET_ACQUISITIONS,
        add=(L.ACQUISITIONS,),
        subtract=(L.DIVESTMENTS,),
        note="net acquisitions are businesses bought less businesses sold",
    ),
    Relationship(
        total=L.NET_SHARE_REPURCHASES,
        add=(L.SHARE_REPURCHASES,),
        subtract=(L.SHARE_ISSUANCE,),
        note="net buybacks are own shares bought less own shares sold or issued",
    ),
    Relationship(
        total=L.NET_BORROWING,
        add=(L.BORROWINGS_RAISED,),
        subtract=(L.BORROWINGS_REPAID,),
        note="net borrowing is borrowings raised less borrowings repaid",
    ),
    Relationship(
        total=L.INVESTING_CASH_FLOW,
        add=(L.DISPOSALS_OF_FIXED_ASSETS, L.OTHER_INVESTING_CASH_FLOW),
        subtract=(L.CAPITAL_EXPENDITURE, L.INTANGIBLE_CAPITAL_EXPENDITURE, L.NET_ACQUISITIONS),
        note="the investing section: fixed assets bought and sold, businesses bought, the rest",
    ),
    Relationship(
        total=L.FINANCING_CASH_FLOW,
        add=(L.NET_BORROWING, L.OTHER_FINANCING_CASH_FLOW),
        subtract=(
            L.LEASE_REPAYMENTS,
            L.LEASE_INTEREST_PAID_OUTSIDE_OPERATING,
            L.INTEREST_PAID_OUTSIDE_OPERATING,
            L.DIVIDENDS_PAID,
            L.CAPITAL_REPAYMENTS_PAID,
            L.DIVIDENDS_TO_MINORITIES,
            L.NET_SHARE_REPURCHASES,
            L.ACQUISITION_OF_MINORITIES,
        ),
        note="the financing section: lenders, lessors, shareholders, minorities, the rest",
    ),
    Relationship(
        total=L.CHANGE_IN_CASH,
        add=(
            L.OPERATING_CASH_FLOW,
            L.INVESTING_CASH_FLOW,
            L.FINANCING_CASH_FLOW,
            L.FX_EFFECT_ON_CASH,
        ),
        note="the change in cash is the three sections and the exchange-rate effect",
    ),
)
"""Every relationship Tracesheet knows. Adding one is a row here and a definition check."""
