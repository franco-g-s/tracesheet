import tomllib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tracesheet.providers.toml_out import emit_toml


def test_round_trips_through_the_standard_reader() -> None:
    text = emit_toml(
        {
            "name": 'Acme "Industrie"',
            "count": 3,
            "ok": True,
            "amount": Decimal("12.50"),
            "day": date(2025, 6, 2),
            "skipped": None,
            "items": [
                {
                    "period": {"end": date(2025, 12, 31)},
                    "pages": [1, 2],
                    "at": datetime(2026, 1, 1, tzinfo=UTC),
                },
            ],
        }
    )
    data = tomllib.loads(text)
    assert data["name"] == 'Acme "Industrie"'
    assert data["count"] == 3
    assert data["ok"] is True
    assert data["amount"] == "12.50"
    assert data["day"] == date(2025, 6, 2)
    assert "skipped" not in data
    assert data["items"][0]["period"]["end"] == date(2025, 12, 31)
    assert data["items"][0]["pages"] == [1, 2]


def test_float_is_refused() -> None:
    with pytest.raises(TypeError, match="float"):
        emit_toml({"amount": 1.5})


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(TypeError, match="timezone"):
        emit_toml({"at": datetime(2026, 1, 1)})  # noqa: DTZ001
