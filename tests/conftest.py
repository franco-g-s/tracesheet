"""Fixtures shared across the test suite."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def acme_root() -> Path:
    """The root holding the fictional Acme company, as a typed-in figures root."""
    return FIXTURES
