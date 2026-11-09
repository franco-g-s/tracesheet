"""Page to HTML: well-formed, self-contained, every link resolving, nothing judging."""

import re
from html.parser import HTMLParser

from tracesheet.model import Evaluation
from tracesheet.report.build import build_page
from tracesheet.report.render import render

VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)


class Balance(HTMLParser):
    """Records every mismatched or unclosed tag."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes {self.stack[-1:] or 'nothing'}")
            return
        self.stack.pop()


def test_the_html_is_well_formed(acme_evaluation: Evaluation) -> None:
    parser = Balance()
    parser.feed(render(build_page(acme_evaluation)))
    parser.close()

    assert parser.errors == []
    assert parser.stack == []


def test_no_judging_classes(acme_evaluation: Evaluation) -> None:
    html = render(build_page(acme_evaluation))

    assert not re.search(r'class="(pass|fail|good|bad|red|green|warn)', html)
    assert not re.search(r'class="[^"]*\b(pass|fail|good|bad|red|green|warn)', html)


def test_every_source_link_has_its_target(acme_evaluation: Evaluation) -> None:
    html = render(build_page(acme_evaluation))
    links = set(re.findall(r'href="#(src-[0-9a-f]+)"', html))
    targets = set(re.findall(r'id="(src-[0-9a-f]+)"', html))

    assert links
    assert links <= targets


def test_the_sections_appear_in_the_sheet_order(acme_evaluation: Evaluation) -> None:
    html = render(build_page(acme_evaluation))
    headings = re.findall(r"<h2[^>]*>([^<]+)</h2>", html)

    assert headings == [
        "Overview",
        "Growth",
        "Profitability",
        "Cash generation",
        "Balance sheet",
        "Shareholder returns",
        "Valuation multiples",
        "Conventions",
        "Sources",
    ]


def test_the_page_is_self_contained(acme_evaluation: Evaluation) -> None:
    html = render(build_page(acme_evaluation))

    assert "<style>" in html
    assert "<script>" in html
    assert not re.search(r'<(link|script)[^>]+(href|src)="(https?:)?//', html)
    assert "@import" not in html
    assert not re.search(r"url\((https?:)?//", html)


def test_text_is_escaped(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    hostile = page.model_copy(update={"multiples_note": "<script>alert(1)</script>"})

    assert "<script>alert(1)</script>" not in render(hostile)


def test_without_a_price_the_rest_still_renders(acme_without_price: Evaluation) -> None:
    html = render(build_page(acme_without_price))

    assert "No price available" in html
    assert "Shareholder returns" in html
    assert "Sources" in html


def test_rendering_is_deterministic(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)

    assert render(page) == render(page)


def test_a_figure_links_to_every_source_beneath_it(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    html = render(page)
    row, cell = next(
        (r, c) for t in page.tables for r in t.rows for c in r.cells if len(c.source_ids) > 1
    )

    row_html = re.search(rf'<tr id="m-{row.key}">.*?</tr>', html, re.DOTALL)
    assert row_html is not None
    for sid in cell.source_ids:
        assert f'href="#src-{sid}"' in row_html.group(0)


def test_older_years_are_marked_for_the_recent_view(acme_evaluation: Evaluation) -> None:
    page = build_page(acme_evaluation)
    padded = page.model_copy(update={"years": tuple(range(2010, 2026))})

    # Only the year headers are checked here: Acme has two years of figures.
    assert 'class="yr older"' not in render(page)
    assert "Last 10 years" in render(padded)
