"""Fetching bytes from a URL, behind a plain function type so tests never touch the network."""

import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

Fetcher = Callable[[str, Mapping[str, str]], bytes]
"""``fetcher(url, headers) -> bytes``. Raises ``FetchError`` on any failure."""

USER_AGENT = "Tracesheet/0.1 (+https://github.com/franco-g-s/tracesheet)"
"""Sent with every request, so a server operator can see who is asking and where to look."""


_SECRET_QUERY = re.compile(r"(?i)([?&](?:api_)?(?:token|key)=)[^&\s#]*")


def redact(text: str) -> str:
    """``text`` with the value of every ``token=``, ``api_token=``, ``key=`` or ``api_key=``
    query parameter replaced by ``***``, so a URL can go into a message without its secret."""
    return _SECRET_QUERY.sub(r"\1***", text)


class FetchError(RuntimeError):
    """A fetch failed, or what came back was not what was expected."""


def urllib_fetch(url: str, headers: Mapping[str, str], timeout_seconds: int = 60) -> bytes:
    """Fetch an https URL with the project's User-Agent and return the body as bytes."""
    if not url.startswith("https://"):
        msg = redact(f"{url}: only https URLs are fetched")
        raise FetchError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return bytes(response.read())
    except urllib.error.URLError as error:
        msg = redact(f"{url}: {error}")
        # Not chained: the original error may carry the full URL, secret included.
        raise FetchError(msg) from None
