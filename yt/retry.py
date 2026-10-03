"""Retry a YouTube fetch with another client when YouTube's video servers answer 403."""

from collections.abc import Callable
from logging import Logger
from urllib.error import HTTPError

CLIENTS: list[dict[str, str]] = [{}, {"client": "MWEB"}]
"""`YTube` kwargs to try, in order: pytubefix's default client, then the mobile web one (the other client that
downloaded reliably in testing)."""


def with_client_retry[T](logger: Logger, fetch: Callable[[dict[str, str]], T]) -> T:
    """Run `fetch(ytube_kwargs)`, retrying with the next client on HTTP 403.

    `fetch` must build a fresh `YTube(url, **ytube_kwargs)`: stream URLs are tied to the client that got them, and
    YouTube occasionally refuses a range request of a download. Other errors are not retried.
    """

    for kwargs, retry in zip(CLIENTS, CLIENTS[1:], strict=False):
        try:
            return fetch(kwargs)
        except HTTPError as e:
            if e.code != 403:
                raise
            logger.warning(
                f"YouTube answered 403 to the {kwargs.get('client', 'default')} client, retrying with {retry['client']}"
            )
    return fetch(CLIENTS[-1])
