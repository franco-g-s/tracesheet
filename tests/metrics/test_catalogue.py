"""The catalogue: one definition per measure, and the conventions they share."""

from tracesheet.metrics.catalogue import (
    CAGR_KEYS,
    CATALOGUE,
    CONVENTIONS,
    Kind,
    Section,
)

KEYS = [
    "revenue",
    "ebit",
    "net_income",
    "revenue_growth",
    "ebit_growth",
    "net_income_growth",
    "eps_growth",
    "fcf_per_share_growth",
    "gross_margin",
    "ebitda_margin",
    "ebit_margin",
    "net_margin",
    "roe",
    "roa",
    "roic",
    "operating_cash_flow",
    "capex",
    "fcf",
    "fcf_conversion",
    "capex_to_revenue",
    "net_debt",
    "net_debt_to_ebitda",
    "equity_ratio",
    "current_ratio",
    "dps",
    "special_dps",
    "payout_ratio",
    "buybacks",
    "diluted_share_change",
    "eps_diluted",
    "fcf_per_share",
    "bvps",
]


def test_the_catalogue_holds_exactly_the_textbook_measures() -> None:
    assert [m.key for m in CATALOGUE] == KEYS


def test_every_definition_is_complete() -> None:
    for m in CATALOGUE:
        assert m.label and m.formula, m.key
        assert isinstance(m.section, Section) and isinstance(m.kind, Kind)


def test_growth_measures_point_at_a_catalogue_key() -> None:
    keys = {m.key for m in CATALOGUE}
    growth = [m for m in CATALOGUE if m.growth_of is not None]
    assert {m.key for m in growth} == {
        "revenue_growth",
        "ebit_growth",
        "net_income_growth",
        "eps_growth",
        "fcf_per_share_growth",
    }
    for m in growth:
        assert m.growth_of in keys
        assert m.section is Section.GROWTH and m.kind is Kind.PERCENT


def test_cagr_keys_are_catalogue_keys() -> None:
    assert CAGR_KEYS == ("revenue", "ebit", "net_income", "eps_diluted", "fcf_per_share")
    assert set(CAGR_KEYS) <= {m.key for m in CATALOGUE}


def test_every_section_has_a_measure() -> None:
    assert {m.section for m in CATALOGUE} == set(Section)


def test_conventions_cover_the_shared_choices() -> None:
    topics = [topic for topic, _ in CONVENTIONS]
    assert len(topics) == len(set(topics))
    for needed in (
        "Revenue",
        "Capex",
        "Earnings and equity",
        "NOPAT",
        "Invested capital",
        "Averages",
        "Net debt",
        "Shares",
        "Dividends",
        "EV",
        "Currency",
        "Undefined",
    ):
        assert needed in topics
    assert all(text.strip() for _, text in CONVENTIONS)
