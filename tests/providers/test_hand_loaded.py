import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from tracesheet.model import ActionKind, CompanyId, Currency, LineItemName, Money, ShareCount
from tracesheet.providers.hand_loaded import FiguresIn, HandLoaded, HandLoadedError

ACME = CompanyId("acme")


def _copy(acme_root: Path, tmp_path: Path) -> Path:
    root = tmp_path / "companies"
    shutil.copytree(acme_root, root)
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_loads_the_fixture_company(acme_root: Path) -> None:
    hl = HandLoaded(acme_root)
    assert hl.companies() == (CompanyId("acme"),)
    records = hl.financial_records(CompanyId("acme"))
    assert [r.period.end.year for r in records] == [2024, 2025]


def test_company_identity(acme_root: Path) -> None:
    company = HandLoaded(acme_root).company(ACME)
    assert company.name == "Acme Industrie AG"
    assert company.currency is Currency.CHF
    assert company.listing.isin == "CH0999999995"
    assert company.share_classes == ("registered",)


def test_figures_are_scaled_to_full_units(acme_root: Path) -> None:
    record = HandLoaded(acme_root).financial_records(ACME)[1]
    assert record.get(LineItemName.REVENUE) == Money(
        amount=Decimal("905000000"), currency=Currency.CHF
    )
    assert record.get(LineItemName.SHARES_DILUTED) == ShareCount(count=Decimal("20000000"))
    assert record.get(LineItemName.EPS_DILUTED) == Money(
        amount=Decimal("4.32"), currency=Currency.CHF
    )
    revenue = next(i for i in record.line_items if i.name is LineItemName.REVENUE)
    assert revenue.label == "Net sales"
    assert revenue.page == 62
    assert revenue.precision == Decimal("100000.0")
    assert record.source.sha256 is not None
    assert record.source.reference == "acme/fy2025.toml"


def test_figures_in_has_three_scales() -> None:
    assert [scale.value for scale in FiguresIn] == ["units", "thousands", "millions"]


def test_fixture_actions_hold_the_split(acme_root: Path) -> None:
    (split,) = HandLoaded(acme_root).actions(ACME)
    assert split.kind is ActionKind.SPLIT
    assert (split.new_shares, split.old_shares) == (2, 1)
    assert split.ratio == Decimal(2)
    assert split.confirmed
    assert split.document is not None
    assert split.document.sha256.startswith("1657ca1ab2df")
    assert split.quote is not None and "1:2" in split.quote


def test_no_actions_file_means_no_actions(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    (root / "acme" / "actions.toml").unlink()
    assert HandLoaded(root).actions(ACME) == ()


@pytest.mark.parametrize("table", ["covered", "dismissed"])
def test_review_tables_in_actions_file_are_refused(
    acme_root: Path, tmp_path: Path, table: str
) -> None:
    root = _copy(acme_root, tmp_path)
    path = root / "acme" / "actions.toml"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f'\n[[{table}]]\nreason = "left over"\n')
    with pytest.raises(HandLoadedError, match=table):
        HandLoaded(root).actions(ACME)


def test_action_from_an_unregistered_document_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    _edit(root / "acme" / "actions.toml", 'sha256 = "1657ca', 'sha256 = "0657ca')
    with pytest.raises(HandLoadedError, match=r"not in documents\.toml"):
        HandLoaded(root).actions(ACME)


def test_unknown_key_in_company_file_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    with (root / "acme" / "company.toml").open("a", encoding="utf-8") as handle:
        handle.write('region = "Europe"\n')
    with pytest.raises(HandLoadedError, match="region"):
        HandLoaded(root).company(ACME)


def test_unknown_key_in_record_file_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    _edit(root / "acme" / "fy2024.toml", 'name = "revenue"\n', 'name = "revenue"\nreviewer = "x"\n')
    with pytest.raises(HandLoadedError, match="reviewer") as raised:
        HandLoaded(root).financial_records(ACME)
    assert raised.value.line_item == "revenue"


def test_unquoted_amount_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    _edit(root / "acme" / "fy2024.toml", 'value = "820.0"', "value = 820.0")
    with pytest.raises(HandLoadedError, match="quotes"):
        HandLoaded(root).financial_records(ACME)


def test_record_in_the_wrong_directory_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    _edit(root / "acme" / "fy2024.toml", 'company = "acme"', 'company = "other"')
    with pytest.raises(HandLoadedError, match="other"):
        HandLoaded(root).financial_records(ACME)


def test_directory_without_company_file_is_refused(acme_root: Path, tmp_path: Path) -> None:
    root = _copy(acme_root, tmp_path)
    (root / "stray").mkdir()
    with pytest.raises(HandLoadedError, match=r"company\.toml"):
        HandLoaded(root).companies()


def test_record_that_does_not_tie_is_refused_at_load(acme_root: Path, tmp_path: Path) -> None:
    # A whole printed unit off (one million, in a report in millions) is beyond the
    # rounding of the print, so the loader itself refuses the file.
    root = _copy(acme_root, tmp_path)
    path = root / "acme" / "fy2025.toml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'(name = "total_assets"\nvalue = ")968\.4(")', r"\g<1>1068.4\g<2>", text, count=1
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(HandLoadedError, match="total_assets"):
        HandLoaded(root).financial_records(ACME)


def test_a_stray_labels_file_is_read_as_a_filing_and_refused(
    acme_root: Path, tmp_path: Path
) -> None:
    root = _copy(acme_root, tmp_path)
    (root / "acme" / "labels.toml").write_text('revenue = ["Net sales"]\n', encoding="utf-8")
    with pytest.raises(HandLoadedError, match=r"labels\.toml"):
        HandLoaded(root).financial_records(ACME)
