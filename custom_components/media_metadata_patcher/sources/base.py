"""Interface every metadata source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

import aiohttp


@dataclass(frozen=True)
class Metadata:
    """Now-playing data from a source. Fields left as None are passed through
    from the wrapped media player unchanged."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    image_url: str | None = None
    # Live streams have no meaningful duration or position.
    is_live: bool = False


class MetadataSource(ABC):
    """A provider of metadata for streams a media player can't describe itself.

    To add a source: subclass this in a new module under `sources/`, add it to
    `SOURCES` in `sources/__init__.py`, and add tests under `tests/sources/`.
    """

    #: Stable identifier, stored in config entries; never change it.
    key: ClassVar[str]
    #: Human-readable name shown in the config flow.
    name: ClassVar[str]
    #: How often to refresh metadata while a player is on a matching stream.
    poll_interval: ClassVar[timedelta]

    @abstractmethod
    def match(self, media_content_id: str | None) -> str | None:
        """Return a lookup key if this source handles the stream, else None.

        Must be cheap and must not do I/O: it runs on every state change.
        """

    @abstractmethod
    async def async_fetch(
        self, session: aiohttp.ClientSession, lookup_key: str
    ) -> Metadata | None:
        """Fetch current metadata for `lookup_key`; None if unavailable."""
