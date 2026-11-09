"""Where figures come from: typed-in annual-report files, the documents they were read
from, and the tie-out checks every record must pass before it is used."""

from tracesheet.providers.documents import (
    Document,
    DocumentKind,
    DocumentRegistry,
    DocumentsError,
)
from tracesheet.providers.fetch import Fetcher, FetchError, urllib_fetch
from tracesheet.providers.hand_loaded import FiguresIn, HandLoaded, HandLoadedError
from tracesheet.providers.protocol import Provider
from tracesheet.providers.reconcile import reconcile
from tracesheet.providers.toml_out import emit_toml

__all__ = [
    "Document",
    "DocumentKind",
    "DocumentRegistry",
    "DocumentsError",
    "FetchError",
    "Fetcher",
    "FiguresIn",
    "HandLoaded",
    "HandLoadedError",
    "Provider",
    "emit_toml",
    "reconcile",
    "urllib_fetch",
]
