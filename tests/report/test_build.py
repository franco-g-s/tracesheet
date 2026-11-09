"""Evaluation to page: section order, catalogue coverage, n/m notes and source links."""

from collections import Counter

import pytest

from tracesheet.metrics.catalogue import CAGR_KEYS, CAGR_SPANS, CATALOGUE, CONVENTIONS, Section
from tracesheet.model import Evaluation
from tracesheet.multiples import MULTIPLE_KEYS
from tracesheet.report.build import build_page
from tracesheet.report.page import Page


def all_rows(page: Page) -> list[tuple[str, tuple[str, ...]]]:
    rows = [(row.key, cell.source_ids) for t in page.tables for row in t.rows for cell in row.cells]
    if page.multiples is not None:
        rows += [(r.key, c.source_ids) for r in page.multiples.rows for c in r.cells]
    if page.cagr is not None:
        rows += [(r.key, c.source_ids) for r in page.cagr.rows for c in r.cells]
    return rows


def test_sections_follow_the_sheet_order(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)

    assert [t.section for t in page.tables] == [
        Section.GROWTH,
        Section.PROFITABILITY,
        Section.CASH,
        Section.BALANCE_SHEET,
        Section.SHAREHOLDERS,
    ]
    assert [t.title for t in page.tables] == [
        "Growth",
        "Profitability",
        "Cash generation",
        "Balance sheet",
        "Shareholder returns",
    ]


def test_every_catalogue_key_appears_once_in_catalogue_order(
    acme_evaluation: Evaluation,
) -> None:
    page = build_page(acme_evaluation)
    keys = [row.key for t in page.tables for row in t.rows]

    assert Counter(keys) == Counter(m.key for m in CATALOGUE)
    # Per-share measures close the shareholder returns table, after its own rows.
    shareholders = next(t for t in page.tables if t.section is Section.SHAREHOLDERS)
    assert [r.key for r in shareholders.rows] == [
        m.key for m in CATALOGUE if m.section in (Section.SHAREHOLDERS, Section.PER_SHARE)
    ]
    for table in page.tables:
        assert [r.key for r in table.rows] == [
            m.key for m in CATALOGUE if m.key in {r.key for r in table.rows}
        ]


def test_years_run_oldest_first_and_every_row_has_one_cell_per_year(
    acme_evaluation: Evaluation,
) -> None:
    page = build_page(acme_evaluation)

    assert page.years == (2024, 2025)
    for table in page.tables:
        assert table.years == page.years
        assert all(len(row.cells) == len(page.years) for row in table.rows)


def test_a_not_meaningful_cell_shows_nm_with_its_reason(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    growth = next(t for t in page.tables if t.section is Section.GROWTH)
    revenue_growth = next(r for r in growth.rows if r.key == "revenue_growth")

    first = revenue_growth.cells[0]
    assert first.text == "n/m"
    assert first.note == "no prior year"
    assert first.source_ids == ()
    nm_cells = [c for t in page.tables for r in t.rows for c in r.cells if c.text == "n/m"]
    assert nm_cells
    assert all(c.note for c in nm_cells)


def test_figures_are_formatted_by_kind(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    cells = {
        (r.key, y): c.text
        for t in page.tables
        for r in t.rows
        for y, c in zip(t.years, r.cells, strict=True)
    }

    assert cells[("revenue", 2025)] == "905"  # CHF m, whole millions
    assert cells[("revenue_growth", 2025)].endswith(tuple("0123456789"))
    assert "%" not in cells[("revenue_growth", 2025)]  # the unit column says %


def test_every_source_id_resolves_to_one_entry(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    ids = [s.id for s in page.sources]

    assert len(ids) == len(set(ids))
    referenced = {sid for _, sids in all_rows(page) for sid in sids}
    assert referenced
    assert referenced <= set(ids)
    # Every entry in Sources is used by some figure on the page.
    assert set(ids) == referenced


def test_a_filed_source_carries_document_page_and_quote(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    revenue = next(s for s in page.sources if s.line == "revenue" and s.fiscal_year == 2025)

    assert revenue.document == "acme/fy2025.toml"
    assert revenue.page == 62
    assert revenue.quote == "Net sales"
    assert revenue.sha256 is not None


def test_the_price_appears_in_sources_as_an_observation(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    observed = [s for s in page.sources if s.observed]

    assert any(s.document == "test close" for s in observed)
    assert all(s.fiscal_year is None and s.page is None for s in observed)


def test_multiples_are_one_column_against_the_latest_year(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)

    assert page.multiples is not None
    assert page.multiples.section is None
    assert page.multiples.years == (2025,)
    keys = [r.key for r in page.multiples.rows]
    assert keys[-len(MULTIPLE_KEYS) :] == list(MULTIPLE_KEYS)
    assert "41.20" in page.multiples_note
    assert "2025" in page.multiples_note


def test_without_a_price_there_are_no_multiples_and_the_note_says_so(
    acme_without_price: Evaluation,
) -> None:
    page = build_page(acme_without_price)

    assert page.multiples is None
    assert "no price" in page.multiples_note.lower()
    assert len(page.tables) == 5


def test_compound_growth_covers_the_cagr_keys(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)

    assert page.cagr is not None
    assert page.cagr.spans == CAGR_SPANS
    assert [r.key for r in page.cagr.rows] == list(CAGR_KEYS)
    # Two years of history give no 5- or 10-year rate: each is n/m with a reason.
    assert all(c.text == "n/m" and c.note for r in page.cagr.rows for c in r.cells)


def test_conventions_come_from_the_catalogue(acme_evaluation: Evaluation) -> None:
    assert build_page(acme_evaluation).conventions == CONVENTIONS


@pytest.mark.parametrize("field", ["created_at", "code_version"])
def test_the_page_records_how_it_was_made(acme_evaluation: Evaluation, field: str) -> None:
    page = build_page(acme_evaluation)

    assert getattr(page, field)
    assert page.as_of == acme_evaluation.as_of.date()
    assert page.created_at == acme_evaluation.created_at.date()
