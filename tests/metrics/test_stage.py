"""The metrics stage: textbook measures from normalized figures, each traced or marked n/m."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tracesheet.metrics.catalogue import CAGR_KEYS, CATALOGUE
from tracesheet.metrics.stage import compute_metrics
from tracesheet.model import (
    CompanyId,
    Currency,
    Filed,
    FiscalPeriod,
    LineItemName,
    Money,
    Normalized,
    Observed,
    PeriodFigures,
    PeriodKind,
    RecordId,
    RecordRef,
    ShareCount,
    Source,
    Traced,
    Unit,
)
from tracesheet.model.metrics import MetricValue, NotMeaningful
from tracesheet.normalize import normalize
from tracesheet.providers import HandLoaded

from .conftest import FY2024, FY2025, MakeNormalized, leaf

L = LineItemName


def value(v: MetricValue) -> Decimal:
    """The magnitude of a traced money amount, ratio or count."""
    assert isinstance(v, Traced), v
    if isinstance(v.value, Money):
        return v.value.amount
    if isinstance(v.value, ShareCount):
        return v.value.count
    assert isinstance(v.value, Decimal)
    return v.value


def reason(v: MetricValue) -> str:
    assert isinstance(v, NotMeaningful), v
    return v.reason


# --- Known answers on two hand-built years ---


def test_fcf_subtracts_both_capex_lines(n2: Normalized) -> None:
    # 2025: OCF 500, PPE purchases 120, intangible purchases 30
    y = compute_metrics(n2).years[-1].values
    assert value(y["capex"]) == Decimal(150) and value(y["fcf"]) == Decimal(350)


def test_roic_uses_average_invested_capital(n2: Normalized) -> None:
    # 2024 IC = 1000, 2025 IC = 1200; EBIT 200, tax 40 on PBT 160 -> rate 0.25 -> NOPAT 150
    assert value(compute_metrics(n2).years[-1].values["roic"]) == Decimal(150) / Decimal(1100)


def test_first_year_return_on_average_balance_is_not_meaningful(n2: Normalized) -> None:
    v = compute_metrics(n2).years[0].values["roe"]
    assert isinstance(v, NotMeaningful) and "opening" in v.reason


def test_loss_year_tax_rate_is_not_meaningful(loss_year: Normalized) -> None:
    assert isinstance(compute_metrics(loss_year).years[-1].values["roic"], NotMeaningful)


def _whats(v: MetricValue) -> set[str]:
    assert isinstance(v, Traced), v
    return {o.what for o in v.sources() if isinstance(o, Observed)}


def test_no_constant_enters_a_trail(n2: Normalized) -> None:
    # Every leaf under every value is one of the fixture's lines: nothing minted on the way.
    for y in compute_metrics(n2).years:
        for v in y.values.values():
            if isinstance(v, Traced):
                assert v.sources()
                assert all(isinstance(o, Observed) and o.source == "test" for o in v.sources())


def test_capex_traces_to_exactly_the_two_purchase_lines(n2: Normalized) -> None:
    capex = compute_metrics(n2).years[-1].values["capex"]
    assert _whats(capex) == {"capital_expenditure FY2025", "intangible_capital_expenditure FY2025"}


def test_roic_traces_to_both_balance_sheets(n2: Normalized) -> None:
    whats = _whats(compute_metrics(n2).years[-1].values["roic"])
    for year in (2024, 2025):
        assert f"total_equity FY{year}" in whats
        assert f"cash_and_equivalents FY{year}" in whats
    assert {"lease_liabilities FY2024", "financial_debt FY2024"} <= whats
    assert {"non_current_borrowings FY2025", "current_lease_liabilities FY2025"} <= whats


def test_catalogue_keys_unique_and_every_key_computed(n2: Normalized) -> None:
    keys = [m.key for m in CATALOGUE]
    assert len(keys) == len(set(keys))
    assert set(compute_metrics(n2).years[-1].values) == set(keys)


def test_every_catalogue_value_of_the_second_year(n2: Normalized) -> None:
    y = compute_metrics(n2).years[-1].values
    fcf_per_share_2024 = Decimal(280) / Decimal(100)
    fcf_per_share_2025 = Decimal(350) / Decimal(96)
    expected = {
        "revenue": Decimal(1100),
        "ebit": Decimal(200),
        "net_income": Decimal(120),
        "revenue_growth": Decimal("0.1"),
        "ebit_growth": Decimal("0.25"),
        "net_income_growth": Decimal(0),
        "eps_growth": (Decimal("1.25") - Decimal("1.10")) / Decimal("1.10"),
        "fcf_per_share_growth": (fcf_per_share_2025 - fcf_per_share_2024) / fcf_per_share_2024,
        "gross_margin": Decimal("0.42"),
        "ebitda_margin": Decimal("0.25"),
        "ebit_margin": Decimal(200) / Decimal(1100),
        "net_margin": Decimal(120) / Decimal(1100),
        "roe": Decimal(115) / Decimal(850),
        "roa": Decimal(120) / Decimal(2100),
        "roic": Decimal(150) / Decimal(1100),
        "operating_cash_flow": Decimal(500),
        "capex": Decimal(150),
        "fcf": Decimal(350),
        "fcf_conversion": Decimal(350) / Decimal(120),
        "capex_to_revenue": Decimal(150) / Decimal(1100),
        "net_debt": Decimal(200),
        "net_debt_to_ebitda": Decimal(200) / Decimal(275),
        "equity_ratio": Decimal(1000) / Decimal(2200),
        "current_ratio": Decimal("1.25"),
        "dps": Decimal("0.50"),
        "special_dps": Decimal("0.20"),
        "payout_ratio": Decimal("0.4"),
        "buybacks": Decimal(25),
        "diluted_share_change": Decimal("-0.04"),
        "eps_diluted": Decimal("1.25"),
        "fcf_per_share": fcf_per_share_2025,
        "bvps": Decimal(900) / Decimal(95),
    }
    assert set(expected) == {m.key for m in CATALOGUE}
    for key, answer in expected.items():
        assert value(y[key]) == answer, key


def test_units_follow_the_kind(n2: Normalized) -> None:
    y = compute_metrics(n2).years[-1].values
    assert isinstance(y["fcf"], Traced) and y["fcf"].unit is Unit.AMOUNT
    assert isinstance(y["fcf_per_share"], Traced) and y["fcf_per_share"].unit is Unit.PER_SHARE
    assert isinstance(y["roic"], Traced) and y["roic"].unit is Unit.RATIO


# --- Undefined values: named, never clamped or imputed ---


def _without(lines: dict[LineItemName, str], *names: LineItemName) -> dict[LineItemName, str]:
    return {name: text for name, text in lines.items() if name not in names}


def test_first_year_growth_has_no_prior_year(n2: Normalized) -> None:
    first = compute_metrics(n2).years[0].values
    assert "prior year" in reason(first["revenue_growth"])
    assert "prior year" in reason(first["diluted_share_change"])


def test_a_gap_year_is_not_an_opening_balance(make: MakeNormalized) -> None:
    y = compute_metrics(make({2023: FY2024, 2025: FY2025})).years[-1].values
    assert "opening" in reason(y["roic"])
    assert "prior year" in reason(y["revenue_growth"])


def test_growth_from_a_non_positive_prior_is_not_meaningful(make: MakeNormalized) -> None:
    y = compute_metrics(make({2024: {**FY2024, L.EBIT: "-5"}, 2025: FY2025})).years[-1].values
    assert reason(y["ebit_growth"]) == "prior-year EBIT is zero or negative"


def test_zero_denominator_names_the_denominator(make: MakeNormalized) -> None:
    y = (
        compute_metrics(make({2025: {**FY2025, L.CURRENT_LIABILITIES: "0", L.EBITDA: "-1"}}))
        .years[-1]
        .values
    )
    assert reason(y["current_ratio"]) == "current liabilities is zero or negative"
    assert reason(y["net_debt_to_ebitda"]) == "EBITDA is zero or negative"


def test_a_missing_input_says_which_line(make: MakeNormalized) -> None:
    lines = _without(FY2025, L.GROSS_PROFIT)
    y = compute_metrics(make({2025: lines})).years[-1].values
    assert reason(y["gross_margin"]) == "gross profit not filed"


def test_special_dividend_absent_is_not_meaningful(make: MakeNormalized) -> None:
    y = compute_metrics(make({2024: FY2024})).years[-1].values
    assert reason(y["special_dps"]) == "special_dividend_per_share not filed"
    no_dividend = _without(FY2024, L.DIVIDEND_PER_SHARE)
    y = compute_metrics(make({2024: no_dividend})).years[-1].values
    assert reason(y["special_dps"]) == "no dividend filed"


@pytest.mark.parametrize(
    ("line", "key", "words"),
    [
        (L.CAPITAL_EXPENDITURE, "capex", "capital expenditure"),
        (L.INTANGIBLE_CAPITAL_EXPENDITURE, "fcf", "intangible capital expenditure"),
        (L.SHARE_REPURCHASES, "buybacks", "share repurchases"),
    ],
)
def test_a_negative_outflow_is_refused_not_flipped(
    make: MakeNormalized, line: LineItemName, key: str, words: str
) -> None:
    y = compute_metrics(make({2025: {**FY2025, line: "-5"}})).years[-1].values
    assert reason(y[key]) == f"{words} filed as negative; expected an outflow"


def test_missing_intangible_purchases_are_not_assumed_zero(make: MakeNormalized) -> None:
    lines = _without(FY2025, L.INTANGIBLE_CAPITAL_EXPENDITURE)
    y = compute_metrics(make({2025: lines})).years[-1].values
    assert reason(y["capex"]) == "intangible purchases not filed"
    assert reason(y["fcf"]) == "intangible purchases not filed"


def test_intangible_purchases_declared_not_printed_count_as_zero(make: MakeNormalized) -> None:
    lines = _without(FY2025, L.INTANGIBLE_CAPITAL_EXPENDITURE)
    base = make({2025: lines})
    period = base.years[0].period
    not_printed = Traced(
        value=Money.parse("0", Currency.CHF),
        unit=Unit.AMOUNT,
        origin=Filed(
            record=RecordRef(
                id=RecordId("acme-fy2025"),
                company_id=CompanyId("acme"),
                period=period,
                filed_at=datetime(2026, 3, 9, tzinfo=UTC),
            ),
            line_item=L.INTANGIBLE_CAPITAL_EXPENDITURE,
            source=Source(provider="hand-loaded", reference="acme-2025.pdf"),
            page=40,
            not_printed=True,
        ),
    )
    figures = {**base.years[0].figures, L.INTANGIBLE_CAPITAL_EXPENDITURE: not_printed}
    n = base.model_copy(update={"years": (PeriodFigures(period=period, figures=figures),)})
    y = compute_metrics(n).years[-1].values
    assert value(y["capex"]) == Decimal(120)
    assert value(y["fcf"]) == Decimal(380)
    capex = y["capex"]
    assert isinstance(capex, Traced)
    assert not_printed.origin in capex.sources()  # the zero is in the trail, with its page


def _no_leases(lines: dict[LineItemName, str]) -> dict[LineItemName, str]:
    return _without(
        lines, L.LEASE_LIABILITIES, L.NON_CURRENT_LEASE_LIABILITIES, L.CURRENT_LEASE_LIABILITIES
    )


def test_leases_count_zero_before_ifrs_16_and_say_so(make: MakeNormalized) -> None:
    metrics = compute_metrics(make({2017: _no_leases(FY2024), 2018: _no_leases(FY2025)}))
    y = metrics.years[-1].values
    # 2018: net debt = (200 + 100) + 0 - 250
    assert value(y["net_debt"]) == Decimal(50)
    roic = y["roic"]
    assert isinstance(roic, Traced)
    notes = [o for o in roic.sources() if isinstance(o, Observed) and "IFRS 16" in o.what]
    assert len(notes) == 2  # one zero leaf per balance sheet averaged
    assert all(o.what == "no lease liability recognised before IFRS 16" for o in notes)
    assert all(o.source == "accounting standard" for o in notes)


def test_a_year_that_began_before_ifrs_16_counts_leases_as_zero() -> None:
    # A June year end: FY2019 began on 1 July 2018, before IFRS 16 took effect.
    def block(start: date, end: date, lines: dict[LineItemName, str]) -> PeriodFigures:
        figures = {name: leaf(name, text, end.year) for name, text in lines.items()}
        return PeriodFigures(
            period=FiscalPeriod(start=start, end=end, kind=PeriodKind.ANNUAL), figures=figures
        )

    n = Normalized(
        company_id=CompanyId("acme"),
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        currency=Currency.CHF,
        years=(
            block(date(2018, 7, 1), date(2019, 6, 30), _no_leases(FY2025)),
            block(date(2019, 7, 1), date(2020, 6, 30), _no_leases(FY2025)),
        ),
        used=(),
    )
    fy2019, fy2020 = (y.values for y in compute_metrics(n).years)
    assert value(fy2019["net_debt"]) == Decimal(50)
    assert reason(fy2020["net_debt"]) == "lease liabilities not filed"


def test_leases_missing_after_ifrs_16_are_not_meaningful(make: MakeNormalized) -> None:
    y = compute_metrics(make({2024: FY2024, 2025: _no_leases(FY2025)})).years[-1].values
    assert reason(y["net_debt"]) == "lease liabilities not filed"
    assert reason(y["roic"]) == "lease liabilities not filed"


# --- Compound annual growth over 5 and 10 years ---


def _revenue_only(revenue: str) -> dict[LineItemName, str]:
    return {L.REVENUE: revenue}


def test_cagr_over_five_and_ten_years(make: MakeNormalized) -> None:
    metrics = compute_metrics(
        make({2015: _revenue_only("500"), 2020: _revenue_only("800"), 2025: _revenue_only("1000")})
    )
    rev = metrics.cagr["revenue"]
    one = Decimal(1)
    assert value(rev[5]) == (Decimal(1000) / Decimal(800)) ** (one / Decimal(5)) - one
    assert value(rev[10]) == (Decimal(1000) / Decimal(500)) ** (one / Decimal(10)) - one
    assert set(metrics.cagr) == set(CAGR_KEYS)
    assert "not filed" in reason(metrics.cagr["ebit"][5])


def test_cagr_without_the_starting_year_is_not_meaningful(make: MakeNormalized) -> None:
    metrics = compute_metrics(make({2024: FY2024, 2025: FY2025}))
    assert "2020" in reason(metrics.cagr["revenue"][5])
    assert "2015" in reason(metrics.cagr["revenue"][10])


def test_cagr_from_a_non_positive_start_is_not_meaningful(make: MakeNormalized) -> None:
    metrics = compute_metrics(make({2020: {L.EBIT: "-3"}, 2025: {L.EBIT: "10"}}))
    assert reason(metrics.cagr["ebit"][5]) == "EBIT is zero or negative in the starting year"


# --- Kühne+Nagel, from the typed-in annual reports ---

ROOT = Path(__file__).parents[2] / "data" / "companies"


@pytest.fixture(scope="module")
def kuehne_nagel() -> Normalized:
    provider = HandLoaded(ROOT)
    company = CompanyId("kuehne-nagel")
    return normalize(
        provider.company(company),
        provider.financial_records(company),
        datetime(2026, 11, 1, tzinfo=UTC),
        actions=provider.actions(company),
    )


def test_kuehne_nagel_every_year_from_2006_has_fcf_and_roic(kuehne_nagel: Normalized) -> None:
    metrics = compute_metrics(kuehne_nagel)
    years = {y.fiscal_year: y.values for y in metrics.years}
    assert set(years) >= set(range(2006, 2026))
    for year in range(2006, 2026):
        for key in ("fcf", "roic"):
            assert isinstance(years[year][key], Traced), (year, key, years[year][key])
        assert value(years[year]["capex"]) >= 0, year


def test_kuehne_nagel_capex_adds_both_purchase_lines(kuehne_nagel: Normalized) -> None:
    y2025 = next(y for y in compute_metrics(kuehne_nagel).years if y.fiscal_year == 2025)
    # 2025: purchases of property, plant and equipment 232, of intangible assets 7 (CHF m)
    assert value(y2025.values["capex"]) == Decimal(239_000_000)


def test_the_ifrs_16_leaf_is_the_same_on_every_run(make: MakeNormalized) -> None:
    # The zero leaf is dated by the period end, so its traced id never moves between runs.
    years = {2017: _no_leases(FY2024), 2018: _no_leases(FY2025)}
    first = compute_metrics(make(years)).years[-1].values["roic"]
    second = compute_metrics(make(years)).years[-1].values["roic"]
    assert isinstance(first, Traced) and isinstance(second, Traced)
    assert first.id == second.id
