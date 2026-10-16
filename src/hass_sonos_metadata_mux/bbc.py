"""BBC Sounds now-playing via the (unofficial) RMS API used by the Sounds web app.

When a Sonos plays a BBC Sounds live stream it reports no metadata, but the
stream URI names the BBC service (e.g. `bbc_radio_two`), which is all the RMS
API needs.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

RMS_BASE = "https://rms.api.bbc.co.uk/v2"

# Where the service id appears in the URIs a Sonos reports for BBC streams:
#   x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/.../vpid/bbc_radio_two/...
#   hls-radio://https://a.files.bbci.co.uk/.../bbc_radio_two.m3u8
_SERVICE_PATTERNS = (
    re.compile(r"bbc\.co\.uk/mediaselector/.*/vpid/(bbc_[a-z0-9_]+)"),
    re.compile(r"bbci\.co\.uk/.*/(bbc_[a-z0-9_]+)\.m3u8"),
)


def service_id_from_uris(uris: Iterable[str]) -> str | None:
    """Return the BBC service id from a Sonos track/media URI, if it is one."""
    for uri in uris:
        for pattern in _SERVICE_PATTERNS:
            if match := pattern.search(uri):
                return match.group(1)
    return None


def _image(template: str | None, size: str) -> str | None:
    """Fill the `{recipe}` size placeholder in an ichef image URL."""
    return template.replace("{recipe}", size) if template else None


def _logo(template: str | None) -> str | None:
    """Fill a network logo template (`{type}_{size}.{format}`) with a square PNG."""
    if not template:
        return None
    return (
        template.replace("{type}", "blocks-colour")
        .replace("{size}", "600x600")
        .replace("{format}", "png")
    )


@dataclass(frozen=True)
class Programme:
    station: str
    title: str
    subtitle: str
    image_url: str | None
    logo_url: str | None


@dataclass(frozen=True)
class Track:
    artist: str
    title: str
    image_url: str | None


@dataclass(frozen=True)
class BbcNowPlaying:
    service_id: str
    programme: Programme | None
    track: Track | None


def parse_broadcasts(data: dict[str, Any], now: datetime, image_size: str) -> Programme | None:
    """Pick the broadcast on air at `now` from a `broadcasts/poll` response."""
    for item in data.get("data", []):
        try:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= now < end:
            continue
        titles = item.get("titles") or {}
        network = item.get("network") or {}
        return Programme(
            station=network.get("short_title") or item.get("service_id", ""),
            title=titles.get("primary") or "",
            subtitle=titles.get("secondary") or "",
            image_url=_image(item.get("image_url"), image_size),
            logo_url=_logo(network.get("logo_url")),
        )
    return None


def parse_segments(data: dict[str, Any], image_size: str) -> Track | None:
    """Return the now-playing music track from a `segments/latest` response.

    Talk programmes return no segments, and the latest segment stays listed
    after it finishes, so only an item flagged `now_playing` counts.
    """
    for item in data.get("data", []):
        if not (item.get("offset") or {}).get("now_playing"):
            continue
        titles = item.get("titles") or {}
        return Track(
            artist=titles.get("primary") or "",
            title=titles.get("secondary") or "",
            image_url=_image(item.get("image_url"), image_size),
        )
    return None


class BbcClient:
    """Fetches now-playing for a BBC service."""

    def __init__(self, session: aiohttp.ClientSession, image_size: str = "640x640"):
        self._session = session
        self._image_size = image_size

    async def _get(self, path: str, **params: str) -> dict[str, Any] | None:
        try:
            async with self._session.get(
                f"{RMS_BASE}/{path}",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("BBC %s returned HTTP %s", path, resp.status)
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as ex:
            _LOGGER.warning("BBC %s request failed: %s", path, ex)
            return None

    async def now_playing(self, service_id: str) -> BbcNowPlaying:
        broadcasts, segments = await asyncio.gather(
            self._get(f"broadcasts/poll/{service_id}"),
            self._get(
                f"services/{service_id}/segments/latest",
                experience="domestic",
                offset="0",
                limit="1",
            ),
        )
        now = datetime.now(UTC)
        return BbcNowPlaying(
            service_id=service_id,
            programme=parse_broadcasts(broadcasts, now, self._image_size) if broadcasts else None,
            track=parse_segments(segments, self._image_size) if segments else None,
        )
