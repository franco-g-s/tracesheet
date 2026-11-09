"""Acme evaluations for the sheet: one with a close, one without."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tracesheet.evaluate import evaluate
from tracesheet.model import CompanyId, Currency, Evaluation, Money, PriceObservation
from tracesheet.providers.hand_loaded import HandLoaded

ACME = CompanyId("acme")
AS_OF = datetime(2026, 6, 30, tzinfo=UTC)
CREATED = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)


@pytest.fixture
def acme_evaluation(acme_root: Path) -> Evaluation:
    """Acme as of 30 June 2026, with a close of CHF 41.20 that day."""
    listing = HandLoaded(acme_root).company(ACME).listing
    price = PriceObservation(
        company_id=ACME,
        listing=listing,
        date=date(2026, 6, 30),
        close=Money(amount=Decimal("41.20"), currency=Currency.CHF),
        source="test close",
        retrieved_at=datetime(2026, 6, 30, 18, tzinfo=UTC),
    )
    return evaluate(acme_root, ACME, AS_OF, price, created_at=CREATED)


@pytest.fixture
def acme_without_price(acme_root: Path) -> Evaluation:
    """Acme as of 30 June 2026, with no close at all."""
    return evaluate(acme_root, ACME, AS_OF, None, created_at=CREATED)
