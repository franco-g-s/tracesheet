"""Fixtures shared across the test suite."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from tracesheet.model import Company, CompanyId, CorporateAction, FinancialRecord
from tracesheet.providers.hand_loaded import HandLoaded

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class Loaded:
    """One company as the typed-in figures provider hands it over."""

    company: Company
    records: tuple[FinancialRecord, ...]
    actions: tuple[CorporateAction, ...]


@pytest.fixture
def acme_root() -> Path:
    """The root holding the fictional Acme company, as a typed-in figures root."""
    return FIXTURES


@pytest.fixture
def acme(acme_root: Path) -> Loaded:
    """Acme's identity, its two annual records and its 1:2 split of 2 June 2025."""
    provider = HandLoaded(acme_root)
    company_id = CompanyId("acme")
    return Loaded(
        company=provider.company(company_id),
        records=tuple(provider.financial_records(company_id)),
        actions=tuple(provider.actions(company_id)),
    )
