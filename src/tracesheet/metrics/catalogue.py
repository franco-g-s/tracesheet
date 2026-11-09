"""The metric catalogue: textbook measures, each with one formula and one plain-language label.

The catalogue describes; it judges nothing. There are no thresholds and no notion of a good
or bad value. ``formula`` is the human-readable definition shown on the sheet and in the
metrics documentation; ``CONVENTIONS`` records the choices several measures share, such as
what capex includes or which share count a per-share figure divides by.
"""

from dataclasses import dataclass
from enum import StrEnum


class Section(StrEnum):
    """Where a measure appears on the sheet, in the sheet's order."""

    GROWTH = "growth"
    PROFITABILITY = "profitability"
    CASH = "cash"
    BALANCE_SHEET = "balance_sheet"
    SHAREHOLDERS = "shareholders"
    PER_SHARE = "per_share"


class Kind(StrEnum):
    """How a measure's value reads: a percentage, an amount, money per share, a multiple
    (shown as "2.4x") or a count."""

    PERCENT = "percent"
    AMOUNT = "amount"
    PER_SHARE = "per_share"
    MULTIPLE = "multiple"
    COUNT = "count"


@dataclass(frozen=True)
class MetricDef:
    """One measure: its key, its label, where it goes, how it reads and how it is computed.

    ``growth_of`` is set on a year-on-year growth measure and names the measure it is the
    growth of.
    """

    key: str
    label: str
    section: Section
    kind: Kind
    formula: str
    growth_of: str | None = None


_GROWTH_FORMULA = "(this year − prior year) ÷ prior year; n/m when the prior year is ≤ 0"

CATALOGUE: tuple[MetricDef, ...] = (
    # Growth: the top lines, and how fast they move
    MetricDef("revenue", "Revenue", Section.GROWTH, Kind.AMOUNT, "Revenue as filed"),
    MetricDef(
        "ebit", "EBIT", Section.GROWTH, Kind.AMOUNT, "Earnings before interest and taxes, as filed"
    ),
    MetricDef(
        "net_income",
        "Net income",
        Section.GROWTH,
        Kind.AMOUNT,
        "Profit for the year, including minorities' share, as filed",
    ),
    MetricDef(
        "revenue_growth",
        "Revenue growth",
        Section.GROWTH,
        Kind.PERCENT,
        f"Revenue: {_GROWTH_FORMULA}",
        growth_of="revenue",
    ),
    MetricDef(
        "ebit_growth",
        "EBIT growth",
        Section.GROWTH,
        Kind.PERCENT,
        f"EBIT: {_GROWTH_FORMULA}",
        growth_of="ebit",
    ),
    MetricDef(
        "net_income_growth",
        "Net income growth",
        Section.GROWTH,
        Kind.PERCENT,
        f"Net income: {_GROWTH_FORMULA}",
        growth_of="net_income",
    ),
    MetricDef(
        "eps_growth",
        "Diluted EPS growth",
        Section.GROWTH,
        Kind.PERCENT,
        f"Diluted EPS: {_GROWTH_FORMULA}",
        growth_of="eps_diluted",
    ),
    MetricDef(
        "fcf_per_share_growth",
        "FCF per share growth",
        Section.GROWTH,
        Kind.PERCENT,
        f"FCF per share: {_GROWTH_FORMULA}",
        growth_of="fcf_per_share",
    ),
    # Profitability
    MetricDef(
        "gross_margin",
        "Gross margin",
        Section.PROFITABILITY,
        Kind.PERCENT,
        "Gross profit ÷ revenue",
    ),
    MetricDef(
        "ebitda_margin", "EBITDA margin", Section.PROFITABILITY, Kind.PERCENT, "EBITDA ÷ revenue"
    ),
    MetricDef("ebit_margin", "EBIT margin", Section.PROFITABILITY, Kind.PERCENT, "EBIT ÷ revenue"),
    MetricDef(
        "net_margin", "Net margin", Section.PROFITABILITY, Kind.PERCENT, "Net income ÷ revenue"
    ),
    MetricDef(
        "roe",
        "Return on equity",
        Section.PROFITABILITY,
        Kind.PERCENT,
        "Net income attributable to shareholders ÷ average equity attributable to "
        "shareholders (total equity − non-controlling interests)",
    ),
    MetricDef(
        "roa",
        "Return on assets",
        Section.PROFITABILITY,
        Kind.PERCENT,
        "Net income ÷ average total assets",
    ),
    MetricDef(
        "roic",
        "Return on invested capital",
        Section.PROFITABILITY,
        Kind.PERCENT,
        "NOPAT ÷ average invested capital, where NOPAT = EBIT × (1 − income tax ÷ profit "
        "before tax) and invested capital = total equity + financial debt + lease "
        "liabilities − cash and equivalents",
    ),
    # Cash generation
    MetricDef(
        "operating_cash_flow",
        "Operating cash flow",
        Section.CASH,
        Kind.AMOUNT,
        "Net cash from operating activities, as filed",
    ),
    MetricDef(
        "capex",
        "Capex",
        Section.CASH,
        Kind.AMOUNT,
        "Purchases of property, plant and equipment + purchases of intangible assets",
    ),
    MetricDef("fcf", "Free cash flow", Section.CASH, Kind.AMOUNT, "Operating cash flow − capex"),
    MetricDef(
        "fcf_conversion",
        "FCF conversion",
        Section.CASH,
        Kind.PERCENT,
        "Free cash flow ÷ net income",
    ),
    MetricDef(
        "capex_to_revenue", "Capex to revenue", Section.CASH, Kind.PERCENT, "Capex ÷ revenue"
    ),
    # Balance sheet
    MetricDef(
        "net_debt",
        "Net debt",
        Section.BALANCE_SHEET,
        Kind.AMOUNT,
        "Financial debt + lease liabilities − cash and equivalents; negative is net cash",
    ),
    MetricDef(
        "net_debt_to_ebitda",
        "Net debt to EBITDA",
        Section.BALANCE_SHEET,
        Kind.MULTIPLE,
        "Net debt ÷ EBITDA",
    ),
    MetricDef(
        "equity_ratio",
        "Equity ratio",
        Section.BALANCE_SHEET,
        Kind.PERCENT,
        "Total equity ÷ total assets",
    ),
    MetricDef(
        "current_ratio",
        "Current ratio",
        Section.BALANCE_SHEET,
        Kind.MULTIPLE,
        "Current assets ÷ current liabilities",
    ),
    # Shareholder returns
    MetricDef(
        "dps",
        "Dividend per share",
        Section.SHAREHOLDERS,
        Kind.PER_SHARE,
        "The ordinary dividend for the fiscal year, as proposed",
    ),
    MetricDef(
        "payout_ratio",
        "Payout ratio",
        Section.SHAREHOLDERS,
        Kind.PERCENT,
        "Dividend per share ÷ diluted EPS",
    ),
    MetricDef(
        "buybacks",
        "Share buybacks",
        Section.SHAREHOLDERS,
        Kind.AMOUNT,
        "Cash paid to buy back the company's own shares, from the cash-flow statement",
    ),
    MetricDef(
        "diluted_share_change",
        "Change in diluted shares",
        Section.SHAREHOLDERS,
        Kind.PERCENT,
        "Diluted weighted average shares: (this year − prior year) ÷ prior year",
    ),
    # Per share
    MetricDef(
        "eps_diluted",
        "Diluted EPS",
        Section.PER_SHARE,
        Kind.PER_SHARE,
        "Diluted earnings per share, as filed",
    ),
    MetricDef(
        "fcf_per_share",
        "FCF per share",
        Section.PER_SHARE,
        Kind.PER_SHARE,
        "Free cash flow ÷ diluted weighted average shares",
    ),
    MetricDef(
        "bvps",
        "Book value per share",
        Section.PER_SHARE,
        Kind.PER_SHARE,
        "Equity attributable to shareholders ÷ year-end shares outstanding",
    ),
)
"""Every measure on the sheet, in the sheet's order."""

CAGR_KEYS: tuple[str, ...] = ("revenue", "ebit", "net_income", "eps_diluted", "fcf_per_share")
"""The measures whose compound annual growth over 5 and 10 years is computed."""

CAGR_SPANS: tuple[int, ...] = (5, 10)
"""The spans, in fiscal years, of the compound annual growth rates."""

CONVENTIONS: tuple[tuple[str, str], ...] = (
    (
        "Revenue",
        "The filed top line. Margins divide by it. Gross margin is gross profit ÷ revenue.",
    ),
    (
        "Capex",
        "Purchases of property, plant and equipment plus purchases of intangible assets, both "
        "from the cash-flow statement: the common analyst definition. Both are held as "
        "positive outflows. Intangible purchases count as zero only where the report is "
        "recorded as printing no such line; otherwise capex is n/m. Free cash flow = "
        "operating cash flow − capex, used consistently in FCF growth, conversion, per share "
        "and yield.",
    ),
    ("FCF conversion", "Free cash flow ÷ net income, both consolidated."),
    (
        "Earnings and equity",
        "Attributable to the parent's shareholders for EPS, return on equity, payout ratio and "
        "book value per share. Consolidated (including minorities) for margins, return on "
        "assets and FCF conversion.",
    ),
    (
        "NOPAT",
        "EBIT × (1 − effective tax rate), with effective rate = income tax ÷ profit before tax. "
        "Undefined when profit before tax ≤ 0.",
    ),
    (
        "Invested capital",
        "Total equity + financial debt + lease liabilities − cash and equivalents. Financial "
        "debt is the filed total, or else current plus non-current borrowings.",
    ),
    (
        "Lease liabilities",
        "The filed total, or else current plus non-current lease liabilities. Before IFRS 16 "
        "(fiscal years before 2019) leases were not on the balance sheet: where none is filed, "
        "they count as zero, and the trail says so. The first IFRS 16 year therefore averages "
        "an opening balance without leases with a closing balance that has them.",
    ),
    (
        "Averages",
        "Return on equity, on assets and on invested capital use the average of opening and "
        "closing balances. The first year shown, and any year after a gap, has no opening "
        "balance, so they are undefined there.",
    ),
    (
        "Net debt",
        "Financial debt + lease liabilities − cash and equivalents. It may be negative (net cash).",
    ),
    (
        "Shares",
        "Per-share figures use the diluted weighted average for the year. Book value per "
        "share and market capitalisation use year-end shares outstanding, net of treasury "
        "shares. Every per-share figure and count is on one share basis across the years.",
    ),
    (
        "Dividends",
        "Dividend per share is the ordinary dividend for the fiscal year, as proposed. Special "
        "dividends are shown separately. Payout ratio = ordinary dividend per share ÷ diluted "
        "EPS. Buybacks are the cash-flow line.",
    ),
    (
        "EV",
        "Market capitalisation + financial debt + lease liabilities + minorities − cash and "
        "equivalents, from the latest annual balance sheet.",
    ),
    (
        "Currency",
        "Figures stay in the reporting currency. If the share price is in another currency, it "
        "is converted at the ECB rate on the price date, and the rate is shown.",
    ),
    (
        "Growth",
        "Year on year: (this year − prior year) ÷ prior year. Compound annual growth over 5 and "
        "10 years ends in the latest year. Both are undefined when the starting value is zero "
        "or negative; compound growth also when the ending value is.",
    ),
    (
        "Undefined",
        "A zero or negative denominator, or a missing input, gives n/m with the reason. "
        "Nothing is clamped or imputed.",
    ),
)
"""The conventions the measures share, as (topic, convention) pairs, in reading order."""
