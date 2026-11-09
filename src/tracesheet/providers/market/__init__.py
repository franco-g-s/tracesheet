"""Market data: closing prices, corporate actions as a vendor reports them, and exchange
rates.

A second interface beside the financial ``Provider``, because market data is observed on a
day rather than filed for a period. ``LocalPrices`` reads hand-typed closes from a TOML file
and is the default; ``Eodhd`` fetches end-of-day prices when ``TRACESHEET_EODHD_TOKEN`` is
set; ``Ecb`` serves reference exchange rates.
"""

from tracesheet.providers.market.cache import CacheError, MarketCache
from tracesheet.providers.market.ecb import Ecb
from tracesheet.providers.market.eodhd import TOKEN_VARIABLE, Eodhd
from tracesheet.providers.market.local import LocalPrices, LocalPricesError
from tracesheet.providers.market.protocol import ClosingPrices, MarketDataProvider, RatesProvider

__all__ = [
    "TOKEN_VARIABLE",
    "CacheError",
    "ClosingPrices",
    "Ecb",
    "Eodhd",
    "LocalPrices",
    "LocalPricesError",
    "MarketCache",
    "MarketDataProvider",
    "RatesProvider",
]
