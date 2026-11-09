"""FinancialRecord: one reporting period exactly as filed. Never modified. The bottom of
every provenance chain.

Line items are named as the company reports them. The record is a faithful copy of the
filing: anything computed from the printed lines happens later, in normalization, and is
traced back to them.
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, model_validator

from tracesheet.model.base import Model, chain_runs_backwards
from tracesheet.model.dates import FiscalPeriod
from tracesheet.model.ids import CompanyId, RecordId
from tracesheet.model.money import Currency, Money, ShareCount


class LineItemName(StrEnum):
    """Statement lines as filed. The list grows one reviewed line at a time."""

    # Income statement
    REVENUE = "revenue"
    GROSS_PROFIT = "gross_profit"
    EBIT = "ebit"
    NET_INCOME = "net_income"
    DEPRECIATION_AMORTIZATION = "depreciation_amortization"
    GOODWILL_IMPAIRMENT = "goodwill_impairment"
    # Income statement — the finer lines, where a report prints them
    COST_OF_SALES = "cost_of_sales"
    MATERIAL_COSTS = "material_costs"
    CHANGE_IN_INVENTORIES = "change_in_inventories"
    PERSONNEL_EXPENSES = "personnel_expenses"
    OTHER_OPERATING_EXPENSES = "other_operating_expenses"
    OTHER_OPERATING_INCOME = "other_operating_income"
    OWN_WORK_CAPITALISED = "own_work_capitalised"
    RESEARCH_AND_DEVELOPMENT = "research_and_development"
    EBITDA = "ebitda"
    IMPAIRMENT_CHARGES = "impairment_charges"
    RESTRUCTURING_COSTS = "restructuring_costs"
    INTEREST_EXPENSE = "interest_expense"
    INTEREST_INCOME = "interest_income"
    PROFIT_BEFORE_TAX = "profit_before_tax"
    INCOME_TAX_EXPENSE = "income_tax_expense"
    NET_INCOME_ATTRIBUTABLE_TO_OWNERS = "net_income_attributable_to_owners"
    NET_INCOME_ATTRIBUTABLE_TO_MINORITIES = "net_income_attributable_to_minorities"
    EPS_BASIC = "eps_basic"
    EPS_DILUTED = "eps_diluted"
    DIVIDEND_PER_SHARE = "dividend_per_share"
    """The ordinary dividend declared for the year. Never a sum of components."""
    SPECIAL_DIVIDEND_PER_SHARE = "special_dividend_per_share"
    """An extraordinary (special) dividend, printed as its own component."""
    CAPITAL_REPAYMENT_PER_SHARE = "capital_repayment_per_share"
    """A distribution from capital contribution reserves, printed as its own component —
    Swiss, and taxed differently from a dividend."""
    # Cash flow
    OPERATING_CASH_FLOW = "operating_cash_flow"
    CAPITAL_EXPENDITURE = "capital_expenditure"
    ACQUISITIONS = "acquisitions"
    DIVIDENDS_PAID = "dividends_paid"
    SHARE_REPURCHASES = "share_repurchases"
    SHARE_ISSUANCE = "share_issuance"
    CHANGE_IN_WORKING_CAPITAL = "change_in_working_capital"
    NET_BORROWING = "net_borrowing"
    # Cash flow — the investing and financing lines, so each section ties to its total
    INTANGIBLE_CAPITAL_EXPENDITURE = "intangible_capital_expenditure"
    DISPOSALS_OF_FIXED_ASSETS = "disposals_of_fixed_assets"
    BORROWINGS_RAISED = "borrowings_raised"
    BORROWINGS_REPAID = "borrowings_repaid"
    LEASE_REPAYMENTS = "lease_repayments"
    DIVIDENDS_TO_MINORITIES = "dividends_to_minorities"
    ACQUISITION_OF_MINORITIES = "acquisition_of_minorities"
    CAPITAL_REPAYMENTS_PAID = "capital_repayments_paid"
    DIVESTMENTS = "divestments"
    NET_ACQUISITIONS = "net_acquisitions"
    """Businesses bought less businesses sold. Typed where a statement prints only the net;
    otherwise solved from the gross pair."""
    NET_SHARE_REPURCHASES = "net_share_repurchases"
    """Own shares bought less own shares sold or issued. Typed where a statement prints only
    the net; otherwise solved from the gross pair."""
    INTEREST_PAID_OUTSIDE_OPERATING = "interest_paid_outside_operating"
    LEASE_INTEREST_PAID_OUTSIDE_OPERATING = "lease_interest_paid_outside_operating"
    INVESTING_CASH_FLOW = "investing_cash_flow"
    FINANCING_CASH_FLOW = "financing_cash_flow"
    FX_EFFECT_ON_CASH = "fx_effect_on_cash"
    CHANGE_IN_CASH = "change_in_cash"
    OTHER_INVESTING_CASH_FLOW = "other_investing_cash_flow"
    """Never typed: the rest of the investing section, solved from its total."""
    OTHER_FINANCING_CASH_FLOW = "other_financing_cash_flow"
    """Never typed: the rest of the financing section, solved from its total."""
    # Balance sheet
    CASH_AND_EQUIVALENTS = "cash_and_equivalents"
    CURRENT_ASSETS = "current_assets"
    TOTAL_ASSETS = "total_assets"
    INTANGIBLE_ASSETS = "intangible_assets"
    CURRENT_LIABILITIES = "current_liabilities"
    FINANCIAL_DEBT = "financial_debt"
    TOTAL_LIABILITIES = "total_liabilities"
    TOTAL_EQUITY = "total_equity"
    PREFERRED_EQUITY = "preferred_equity"
    GOODWILL = "goodwill"
    OTHER_INTANGIBLE_ASSETS = "other_intangible_assets"
    TRADE_RECEIVABLES = "trade_receivables"
    INVENTORIES = "inventories"
    CAPITALISED_DEVELOPMENT_COSTS = "capitalised_development_costs"
    LEASE_LIABILITIES = "lease_liabilities"
    NON_CURRENT_LEASE_LIABILITIES = "non_current_lease_liabilities"
    CURRENT_LEASE_LIABILITIES = "current_lease_liabilities"
    NON_CURRENT_BORROWINGS = "non_current_borrowings"
    CURRENT_BORROWINGS = "current_borrowings"
    TOTAL_LIABILITIES_AND_EQUITY = "total_liabilities_and_equity"
    NON_CONTROLLING_INTERESTS = "non_controlling_interests"
    RETAINED_EARNINGS = "retained_earnings"
    GOODWILL_OFFSET_AGAINST_EQUITY = "goodwill_offset_against_equity"
    GOODWILL_ACQUIRED = "goodwill_acquired"
    """Goodwill added through acquisitions in the year, from the goodwill note. A movement,
    kept with the balance it rolls forward."""
    # Shares
    SHARES_OUTSTANDING = "shares_outstanding"
    SHARES_BASIC = "shares_basic"
    """The weighted average number of shares over the period, as used for basic EPS."""
    SHARES_DILUTED = "shares_diluted"
    SHARES_REPURCHASED = "shares_repurchased"
    """The number of its own shares the company bought in the period."""


COUNT_LINES = frozenset(
    {
        LineItemName.SHARES_OUTSTANDING,
        LineItemName.SHARES_BASIC,
        LineItemName.SHARES_DILUTED,
        LineItemName.SHARES_REPURCHASED,
    }
)
"""The lines that are counts, not amounts."""

DERIVED_ONLY = frozenset(
    {LineItemName.OTHER_INVESTING_CASH_FLOW, LineItemName.OTHER_FINANCING_CASH_FLOW}
)
"""Lines no report prints as such: always solved from a section total, never typed. A
record that carries one is refused, because a typed remainder would hide a missing line."""

PER_SHARE_LINES = frozenset(
    {
        LineItemName.EPS_BASIC,
        LineItemName.EPS_DILUTED,
        LineItemName.DIVIDEND_PER_SHARE,
        LineItemName.SPECIAL_DIVIDEND_PER_SHARE,
        LineItemName.CAPITAL_REPAYMENT_PER_SHARE,
    }
)
"""Money per one share, as the report prints it. Typed with ``figures_in = "units"``."""


class Statement(StrEnum):
    """Which statement a line belongs to. Flows accrue over a period; balances are a
    snapshot at its end — the distinction currency conversion depends on (IAS 21)."""

    INCOME = "income"
    CASH_FLOW = "cash_flow"
    BALANCE_SHEET = "balance_sheet"
    SHARES = "shares"


STATEMENT: dict[LineItemName, Statement] = {
    LineItemName.REVENUE: Statement.INCOME,
    LineItemName.GROSS_PROFIT: Statement.INCOME,
    LineItemName.EBIT: Statement.INCOME,
    LineItemName.NET_INCOME: Statement.INCOME,
    LineItemName.DEPRECIATION_AMORTIZATION: Statement.INCOME,
    LineItemName.GOODWILL_IMPAIRMENT: Statement.INCOME,
    LineItemName.COST_OF_SALES: Statement.INCOME,
    LineItemName.MATERIAL_COSTS: Statement.INCOME,
    LineItemName.CHANGE_IN_INVENTORIES: Statement.INCOME,
    LineItemName.PERSONNEL_EXPENSES: Statement.INCOME,
    LineItemName.OTHER_OPERATING_EXPENSES: Statement.INCOME,
    LineItemName.OTHER_OPERATING_INCOME: Statement.INCOME,
    LineItemName.OWN_WORK_CAPITALISED: Statement.INCOME,
    LineItemName.RESEARCH_AND_DEVELOPMENT: Statement.INCOME,
    LineItemName.EBITDA: Statement.INCOME,
    LineItemName.IMPAIRMENT_CHARGES: Statement.INCOME,
    LineItemName.RESTRUCTURING_COSTS: Statement.INCOME,
    LineItemName.INTEREST_EXPENSE: Statement.INCOME,
    LineItemName.INTEREST_INCOME: Statement.INCOME,
    LineItemName.PROFIT_BEFORE_TAX: Statement.INCOME,
    LineItemName.INCOME_TAX_EXPENSE: Statement.INCOME,
    LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS: Statement.INCOME,
    LineItemName.NET_INCOME_ATTRIBUTABLE_TO_MINORITIES: Statement.INCOME,
    LineItemName.EPS_BASIC: Statement.INCOME,
    LineItemName.EPS_DILUTED: Statement.INCOME,
    LineItemName.DIVIDEND_PER_SHARE: Statement.INCOME,
    LineItemName.SPECIAL_DIVIDEND_PER_SHARE: Statement.INCOME,
    LineItemName.CAPITAL_REPAYMENT_PER_SHARE: Statement.INCOME,
    LineItemName.OPERATING_CASH_FLOW: Statement.CASH_FLOW,
    LineItemName.CAPITAL_EXPENDITURE: Statement.CASH_FLOW,
    LineItemName.ACQUISITIONS: Statement.CASH_FLOW,
    LineItemName.DIVIDENDS_PAID: Statement.CASH_FLOW,
    LineItemName.SHARE_REPURCHASES: Statement.CASH_FLOW,
    LineItemName.SHARE_ISSUANCE: Statement.CASH_FLOW,
    LineItemName.CHANGE_IN_WORKING_CAPITAL: Statement.CASH_FLOW,
    LineItemName.NET_BORROWING: Statement.CASH_FLOW,
    LineItemName.INTANGIBLE_CAPITAL_EXPENDITURE: Statement.CASH_FLOW,
    LineItemName.DISPOSALS_OF_FIXED_ASSETS: Statement.CASH_FLOW,
    LineItemName.BORROWINGS_RAISED: Statement.CASH_FLOW,
    LineItemName.BORROWINGS_REPAID: Statement.CASH_FLOW,
    LineItemName.LEASE_REPAYMENTS: Statement.CASH_FLOW,
    LineItemName.DIVIDENDS_TO_MINORITIES: Statement.CASH_FLOW,
    LineItemName.ACQUISITION_OF_MINORITIES: Statement.CASH_FLOW,
    LineItemName.CAPITAL_REPAYMENTS_PAID: Statement.CASH_FLOW,
    LineItemName.DIVESTMENTS: Statement.CASH_FLOW,
    LineItemName.NET_ACQUISITIONS: Statement.CASH_FLOW,
    LineItemName.NET_SHARE_REPURCHASES: Statement.CASH_FLOW,
    LineItemName.INTEREST_PAID_OUTSIDE_OPERATING: Statement.CASH_FLOW,
    LineItemName.LEASE_INTEREST_PAID_OUTSIDE_OPERATING: Statement.CASH_FLOW,
    LineItemName.INVESTING_CASH_FLOW: Statement.CASH_FLOW,
    LineItemName.FINANCING_CASH_FLOW: Statement.CASH_FLOW,
    LineItemName.FX_EFFECT_ON_CASH: Statement.CASH_FLOW,
    LineItemName.CHANGE_IN_CASH: Statement.CASH_FLOW,
    LineItemName.OTHER_INVESTING_CASH_FLOW: Statement.CASH_FLOW,
    LineItemName.OTHER_FINANCING_CASH_FLOW: Statement.CASH_FLOW,
    LineItemName.CASH_AND_EQUIVALENTS: Statement.BALANCE_SHEET,
    LineItemName.CURRENT_ASSETS: Statement.BALANCE_SHEET,
    LineItemName.TOTAL_ASSETS: Statement.BALANCE_SHEET,
    LineItemName.INTANGIBLE_ASSETS: Statement.BALANCE_SHEET,
    LineItemName.CURRENT_LIABILITIES: Statement.BALANCE_SHEET,
    LineItemName.FINANCIAL_DEBT: Statement.BALANCE_SHEET,
    LineItemName.TOTAL_LIABILITIES: Statement.BALANCE_SHEET,
    LineItemName.TOTAL_EQUITY: Statement.BALANCE_SHEET,
    LineItemName.PREFERRED_EQUITY: Statement.BALANCE_SHEET,
    LineItemName.GOODWILL: Statement.BALANCE_SHEET,
    LineItemName.OTHER_INTANGIBLE_ASSETS: Statement.BALANCE_SHEET,
    LineItemName.NON_CURRENT_LEASE_LIABILITIES: Statement.BALANCE_SHEET,
    LineItemName.CURRENT_LEASE_LIABILITIES: Statement.BALANCE_SHEET,
    LineItemName.NON_CURRENT_BORROWINGS: Statement.BALANCE_SHEET,
    LineItemName.CURRENT_BORROWINGS: Statement.BALANCE_SHEET,
    LineItemName.TOTAL_LIABILITIES_AND_EQUITY: Statement.BALANCE_SHEET,
    LineItemName.TRADE_RECEIVABLES: Statement.BALANCE_SHEET,
    LineItemName.INVENTORIES: Statement.BALANCE_SHEET,
    LineItemName.CAPITALISED_DEVELOPMENT_COSTS: Statement.BALANCE_SHEET,
    LineItemName.LEASE_LIABILITIES: Statement.BALANCE_SHEET,
    LineItemName.NON_CONTROLLING_INTERESTS: Statement.BALANCE_SHEET,
    LineItemName.RETAINED_EARNINGS: Statement.BALANCE_SHEET,
    LineItemName.GOODWILL_OFFSET_AGAINST_EQUITY: Statement.BALANCE_SHEET,
    LineItemName.GOODWILL_ACQUIRED: Statement.BALANCE_SHEET,
    LineItemName.SHARES_OUTSTANDING: Statement.SHARES,
    LineItemName.SHARES_BASIC: Statement.SHARES,
    LineItemName.SHARES_DILUTED: Statement.SHARES,
    LineItemName.SHARES_REPURCHASED: Statement.SHARES,
}
"""Every line, its statement. A test checks the map is complete."""

DEFINITION: dict[LineItemName, str] = {
    # Income statement. Costs and deductions are held as positive magnitudes; the
    # relationships (tracesheet.model.relationships) carry the signs.
    LineItemName.REVENUE: "Net sales (turnover) after rebates and other price reductions; "
    "for a freight forwarder, "
    "gross turnover including the freight passed through",
    LineItemName.GROSS_PROFIT: "Revenue less cost of sales",
    LineItemName.EBIT: "Operating profit: earnings before interest and taxes, after all "
    "depreciation, amortisation and impairment",
    LineItemName.NET_INCOME: "Profit for the year, owners' and minorities' shares together",
    LineItemName.DEPRECIATION_AMORTIZATION: "All depreciation, amortisation and impairment of "
    "property, plant and equipment, right-of-use assets and intangible assets including "
    "goodwill: everything between EBITDA and EBIT",
    LineItemName.GOODWILL_IMPAIRMENT: "Impairment of goodwill alone; part of depreciation, "
    "amortisation and impairment",
    LineItemName.COST_OF_SALES: "Costs of producing what was sold (by function); for a "
    "forwarder, services bought from third parties",
    LineItemName.MATERIAL_COSTS: "Materials and merchandise, including third-party services "
    "(income statement by nature)",
    LineItemName.CHANGE_IN_INVENTORIES: "Change in inventories of finished goods and work in "
    "progress (income statement by nature), signed as printed",
    LineItemName.PERSONNEL_EXPENSES: "All personnel costs",
    LineItemName.OTHER_OPERATING_EXPENSES: "Operating costs not in another line",
    LineItemName.OTHER_OPERATING_INCOME: "Operating income other than revenue",
    LineItemName.OWN_WORK_CAPITALISED: "Own work capitalised (aktivierte Eigenleistungen)",
    LineItemName.RESEARCH_AND_DEVELOPMENT: "Research and development expense",
    LineItemName.EBITDA: "EBIT before depreciation, amortisation and impairment",
    LineItemName.IMPAIRMENT_CHARGES: "Impairment charges other than goodwill, where printed "
    "separately; part of depreciation, amortisation and impairment",
    LineItemName.RESTRUCTURING_COSTS: "Restructuring costs, where printed separately",
    LineItemName.INTEREST_EXPENSE: "Interest and similar financial expense, including interest "
    "on lease liabilities",
    LineItemName.INTEREST_INCOME: "Interest and similar financial income",
    LineItemName.PROFIT_BEFORE_TAX: "Profit before income tax",
    LineItemName.INCOME_TAX_EXPENSE: "Income tax expense",
    LineItemName.NET_INCOME_ATTRIBUTABLE_TO_OWNERS: "Profit for the year attributable to the "
    "shareholders of the company",
    LineItemName.NET_INCOME_ATTRIBUTABLE_TO_MINORITIES: "Profit for the year attributable to "
    "non-controlling interests",
    LineItemName.EPS_BASIC: "Basic earnings per share, as printed",
    LineItemName.EPS_DILUTED: "Diluted earnings per share, as printed",
    LineItemName.DIVIDEND_PER_SHARE: "The ordinary dividend declared for the year",
    LineItemName.SPECIAL_DIVIDEND_PER_SHARE: "An extraordinary dividend, printed as its own "
    "component",
    LineItemName.CAPITAL_REPAYMENT_PER_SHARE: "A distribution from capital contribution "
    "reserves, printed as its own component",
    # Cash flow
    LineItemName.OPERATING_CASH_FLOW: "Net cash from operating activities",
    LineItemName.CAPITAL_EXPENDITURE: "Purchases of property, plant and equipment, excluding "
    "acquisitions of businesses; intangible assets too where the report prints one line for "
    "both",
    LineItemName.ACQUISITIONS: "Cash paid for businesses acquired, net of cash acquired; never "
    "net of businesses sold (that is net_acquisitions)",
    LineItemName.DIVIDENDS_PAID: "Dividends paid to the company's shareholders",
    LineItemName.SHARE_REPURCHASES: "Cash paid to buy back the company's own shares; never net "
    "of shares sold (that is net_share_repurchases)",
    LineItemName.SHARE_ISSUANCE: "Cash received from issuing new shares or selling treasury shares",
    LineItemName.CHANGE_IN_WORKING_CAPITAL: "Change in working capital in the cash-flow "
    "statement, signed as printed",
    LineItemName.NET_BORROWING: "Borrowings raised less borrowings repaid, leases excluded",
    LineItemName.INTANGIBLE_CAPITAL_EXPENDITURE: "Purchases of intangible assets other than "
    "goodwill, where printed apart from capital_expenditure",
    LineItemName.DISPOSALS_OF_FIXED_ASSETS: "Cash received from selling property, plant and "
    "equipment and intangible assets",
    LineItemName.BORROWINGS_RAISED: "Cash received from new borrowings, leases excluded",
    LineItemName.BORROWINGS_REPAID: "Cash paid to repay borrowings, leases excluded",
    LineItemName.LEASE_REPAYMENTS: "Cash paid to repay the principal of lease liabilities, "
    "interest on them excluded",
    LineItemName.DIVIDENDS_TO_MINORITIES: "Dividends paid to the minority shareholders of "
    "subsidiaries",
    LineItemName.ACQUISITION_OF_MINORITIES: "Cash paid to buy minority holdings in "
    "subsidiaries the company already controls",
    LineItemName.CAPITAL_REPAYMENTS_PAID: "Cash paid to shareholders from capital contribution "
    "reserves, where printed apart from dividends",
    LineItemName.DIVESTMENTS: "Cash received for businesses sold, net of cash disposed of",
    LineItemName.NET_ACQUISITIONS: "Businesses bought less businesses sold; positive when more "
    "was paid than received",
    LineItemName.NET_SHARE_REPURCHASES: "Own shares bought less own shares sold or issued; "
    "positive when more was paid than received",
    LineItemName.INTEREST_PAID_OUTSIDE_OPERATING: "Interest paid on borrowings, where the "
    "statement puts it outside operating activities; none where it is inside them",
    LineItemName.LEASE_INTEREST_PAID_OUTSIDE_OPERATING: "Interest paid on lease liabilities, "
    "where the statement puts it outside operating activities and apart from other interest",
    LineItemName.INVESTING_CASH_FLOW: "Net cash from investing activities, signed as printed",
    LineItemName.FINANCING_CASH_FLOW: "Net cash from financing activities, signed as printed",
    LineItemName.FX_EFFECT_ON_CASH: "Effect of exchange-rate changes on cash, signed as printed",
    LineItemName.CHANGE_IN_CASH: "Increase or decrease in cash as the cash-flow statement "
    "defines cash (it may be net of bank overdrafts), signed as printed",
    LineItemName.OTHER_INVESTING_CASH_FLOW: "Every investing line not typed on its own; never "
    "typed, always solved from the section total",
    LineItemName.OTHER_FINANCING_CASH_FLOW: "Every financing line not typed on its own; never "
    "typed, always solved from the section total",
    # Balance sheet
    LineItemName.CASH_AND_EQUIVALENTS: "Cash and cash equivalents",
    LineItemName.CURRENT_ASSETS: "Total current assets",
    LineItemName.TOTAL_ASSETS: "Total assets",
    LineItemName.INTANGIBLE_ASSETS: "All intangible assets, goodwill included",
    LineItemName.CURRENT_LIABILITIES: "Total current liabilities",
    LineItemName.FINANCIAL_DEBT: "Borrowings that carry interest, current and "
    "non-current, "
    "excluding lease liabilities",
    LineItemName.TOTAL_LIABILITIES: "All liabilities, current and non-current",
    LineItemName.TOTAL_EQUITY: "Total equity, non-controlling interests included",
    LineItemName.PREFERRED_EQUITY: "Preferred equity",
    LineItemName.GOODWILL: "Goodwill carried on the balance sheet",
    LineItemName.OTHER_INTANGIBLE_ASSETS: "Intangible assets other than goodwill",
    LineItemName.TRADE_RECEIVABLES: "Trade receivables",
    LineItemName.INVENTORIES: "Inventories",
    LineItemName.CAPITALISED_DEVELOPMENT_COSTS: "Development costs carried as an asset",
    LineItemName.LEASE_LIABILITIES: "Lease liabilities, current and non-current",
    LineItemName.NON_CURRENT_LEASE_LIABILITIES: "Lease liabilities due after one year",
    LineItemName.CURRENT_LEASE_LIABILITIES: "Lease liabilities due within one year",
    LineItemName.NON_CURRENT_BORROWINGS: "Borrowings that carry interest, due after "
    "one year, "
    "excluding leases",
    LineItemName.CURRENT_BORROWINGS: "Borrowings that carry interest, due within "
    "one year, "
    "excluding leases",
    LineItemName.TOTAL_LIABILITIES_AND_EQUITY: "Total liabilities and equity",
    LineItemName.NON_CONTROLLING_INTERESTS: "Equity attributable to non-controlling interests",
    LineItemName.RETAINED_EARNINGS: "Retained earnings",
    LineItemName.GOODWILL_OFFSET_AGAINST_EQUITY: "Goodwill offset directly against equity "
    "(Swiss GAAP FER), from the notes",
    LineItemName.GOODWILL_ACQUIRED: "Goodwill added through acquisitions in the year, from "
    "the goodwill note's additions row where printed",
    # Shares
    LineItemName.SHARES_OUTSTANDING: "Shares outstanding at the period end, treasury shares "
    "excluded",
    LineItemName.SHARES_BASIC: "Weighted average shares for basic EPS",
    LineItemName.SHARES_DILUTED: "Weighted average shares for diluted EPS",
    LineItemName.SHARES_REPURCHASED: "Own shares bought during the period, from the equity note",
}
"""What every line includes and excludes. A relationship between lines is only correct if
the lines on both sides mean what these say; a test checks every line has one."""


class AuditOpinion(StrEnum):
    """What the auditor signed: an unqualified opinion, or one of the three that are not."""

    UNQUALIFIED = "unqualified"
    QUALIFIED = "qualified"
    ADVERSE = "adverse"
    DISCLAIMER = "disclaimer"


def _sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        msg = f"{value!r} is not a lower-case hex SHA-256"
        raise ValueError(msg)
    return value


Sha256 = Annotated[str, AfterValidator(_sha256)]
"""A file fingerprint, so a page always belongs to an identified document."""


class LineItem(Model):
    """One printed figure, with where on the page to find it."""

    name: LineItemName
    value: Money | ShareCount
    label: str | None = None
    """The report's own wording for this line, so a human can find it on the page."""
    page: int | None = None
    """The page of the report the figure was read from, as printed on the page."""
    pdf_page: int | None = None
    """The page index a PDF viewer needs; the printed folio and the index differ."""
    note: str | None = None
    """What the person who typed it wanted to say: a caveat, a definition, a doubt."""
    share_basis_date: date | None = None
    """The date whose share basis a per-share figure or count is printed on, when the page
    does not follow its filing date — a pre-split count in a later report."""
    share_class: str | None = None
    """The share class a per-share figure or count is for. Absent: the company's only one."""
    precision: Decimal | None = None
    """One unit of the last digit printed, in the line's own unit: 0.1 million for "92.8"
    in a report in millions, a million for "92". None when the source does not say. A later
    filing restates a line only beyond the rounding of the coarser print."""
    not_printed: bool = False
    """The statement has no such line at all: the person loading it read the page and says
    the company had none. A zero with a page to check, never an assumption."""

    @model_validator(mode="after")
    def _counts_are_counts_and_amounts_are_money(self) -> "LineItem":
        if self.not_printed:
            amount = self.value.amount if isinstance(self.value, Money) else self.value.count
            if amount != 0:
                msg = f"{self.name} is declared not printed, so its value must be zero"
                raise ValueError(msg)
        if self.name in COUNT_LINES and not isinstance(self.value, ShareCount):
            msg = f"{self.name} is a count and must hold a ShareCount"
            raise ValueError(msg)
        if self.name not in COUNT_LINES and not isinstance(self.value, Money):
            msg = f"{self.name} is an amount and must hold Money"
            raise ValueError(msg)
        share_based = self.name in COUNT_LINES or self.name in PER_SHARE_LINES
        if not share_based and (self.share_basis_date is not None or self.share_class is not None):
            msg = f"{self.name} is an amount: only per-share and count lines have a share basis"
            raise ValueError(msg)
        return self


class Source(Model):
    """Which provider a record came from, and that provider's own reference for it: for a
    hand-loaded record, the document the figures were read from."""

    provider: str
    reference: str
    sha256: Sha256 | None = None
    """Fingerprint of the document the figures were read from, when it is a file."""


class RecordRef(Model):
    """A dated reference to a record: enough to check ordering without loading it."""

    id: RecordId
    company_id: CompanyId
    period: FiscalPeriod
    filed_at: AwareDatetime


class FinancialRecord(Model):
    """One reporting period of one company, as filed."""

    id: RecordId
    company_id: CompanyId
    period: FiscalPeriod
    filed_at: AwareDatetime
    """When this was published. Required: without it, look-ahead bias is unavoidable."""
    source: Source
    line_items: tuple[LineItem, ...]
    restates: RecordRef | None = None
    """The earlier filing this one supersedes. Both are kept."""
    auditor: str | None = None
    """The audit firm named in the audit report."""
    audit_opinion: AuditOpinion | None = None
    going_concern_emphasis: bool = False
    """The audit report draws attention to a material uncertainty about going concern."""

    @model_validator(mode="after")
    def _consistent(self) -> "FinancialRecord":
        if self.filed_at.date() < self.period.end:
            msg = f"filed {self.filed_at.date()}, before the period ended {self.period.end}"
            raise ValueError(msg)
        names = [item.name for item in self.line_items]
        derived = sorted(set(names) & DERIVED_ONLY)
        if derived:
            msg = f"{', '.join(derived)} is never typed: it is solved from its section total"
            raise ValueError(msg)
        for name in names:
            if names.count(name) > 1:
                msg = f"line item {name} appears twice"
                raise ValueError(msg)
        currencies = {
            item.value.currency for item in self.line_items if isinstance(item.value, Money)
        }
        if not currencies:
            msg = "a record needs at least one amount line item"
            raise ValueError(msg)
        if len(currencies) > 1:
            msg = f"one record is in one currency, not {sorted(currencies)}"
            raise ValueError(msg)
        if self.restates is not None:
            if self.restates.company_id != self.company_id:
                msg = "a restatement must be of the same company"
                raise ValueError(msg)
            if self.restates.filed_at >= self.filed_at:
                raise chain_runs_backwards(
                    f"restates a record filed {self.restates.filed_at.isoformat()}, "
                    f"which is not before this filing {self.filed_at.isoformat()}"
                )
        return self

    @property
    def currency(self) -> Currency:
        return next(
            item.value.currency for item in self.line_items if isinstance(item.value, Money)
        )

    def get(self, name: LineItemName) -> Money | ShareCount | None:
        return next((item.value for item in self.line_items if item.name is name), None)

    def __getitem__(self, name: LineItemName) -> Money | ShareCount:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def ref(self) -> RecordRef:
        return RecordRef(
            id=self.id, company_id=self.company_id, period=self.period, filed_at=self.filed_at
        )
