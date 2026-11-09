"""Fetching bytes from a URL, behind a plain function type so tests never touch the network."""

import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

Fetcher = Callable[[str, Mapping[str, str]], bytes]
"""``fetcher(url, headers) -> bytes``. Raises ``FetchError`` on any failure."""

USER_AGENT = "Tracesheet/0.1 (+https://github.com/franco-g-s/tracesheet)"
"""Sent with every request, so a server operator can see who is asking and where to look."""


class FetchError(RuntimeError):
    """A fetch failed, or what came back was not what was expected."""


def urllib_fetch(url: str, headers: Mapping[str, str], timeout_seconds: int = 60) -> bytes:
    """Fetch an https URL with the project's User-Agent and return the body as bytes."""
    if not url.startswith("https://"):
        msg = f"{url}: only https URLs are fetched"
        raise FetchError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return bytes(response.read())
    except urllib.error.URLError as error:
        msg = f"{url}: {error}"
        raise FetchError(msg) from error
