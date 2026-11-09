"""Exchange rates for one fiscal year: the average for flows, the closing for balances."""

from collections.abc import Sequence

from pydantic import model_validator

from tracesheet.model import Currency, ExchangeRate, Model, Traced, Unit


class YearRates(Model):
    """Both rates are ``Observed`` traced numbers, so a converted figure's trail names them."""

    fiscal_year: int
    average: Traced
    closing: Traced

    @model_validator(mode="after")
    def _both_rates_same_pair(self) -> "YearRates":
        for name, rate in (("average", self.average), ("closing", self.closing)):
            if rate.unit is not Unit.EXCHANGE_RATE:
                msg = f"{name} must be an exchange rate, not {rate.unit}"
                raise ValueError(msg)
        if self.pair != _pair(self.closing):
            msg = "average and closing rates must be for the same currency pair"
            raise ValueError(msg)
        return self

    @property
    def pair(self) -> tuple[Currency, Currency]:
        return _pair(self.average)


def _pair(rate: Traced) -> tuple[Currency, Currency]:
    assert isinstance(rate.value, ExchangeRate)
    return rate.value.base, rate.value.quote


def find_rates(
    rates: Sequence[YearRates], base: Currency, quote: Currency, fiscal_year: int
) -> YearRates | None:
    """The rates converting ``base`` into ``quote`` for ``fiscal_year``, if given."""
    return next(
        (r for r in rates if r.pair == (base, quote) and r.fiscal_year == fiscal_year), None
    )
