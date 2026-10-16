"""BBC Sounds live stations, via the (unofficial) RMS API the Sounds web app uses.

A Sonos (and other players) playing a BBC Sounds live stream reports no
metadata, but the stream URI names the BBC service (e.g. `bbc_radio_two`),
which is all the RMS API needs.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .base import Metadata, MetadataSource

_LOGGER = logging.getLogger(__name__)

RMS_BASE = "https://rms.api.bbc.co.uk/v2"
IMAGE_SIZE = "640x640"

# Where the service id appears in BBC stream URIs:
#   x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/.../vpid/bbc_radio_two/...
#   hls-radio://https://a.files.bbci.co.uk/.../bbc_radio_two.m3u8
_SERVICE_PATTERNS = (
    re.compile(r"bbc\.co\.uk/mediaselector/.*/vpid/(bbc_[a-z0-9_]+)"),
    re.compile(r"bbci\.co\.uk/.*/(bbc_[a-z0-9_]+)\.m3u8"),
)


def service_id_from_uri(uri: str | None) -> str | None:
    """Return the BBC service id from a stream URI, if it is one."""
    if not uri:
        return None
    for pattern in _SERVICE_PATTERNS:
        if match := pattern.search(uri):
            return match.group(1)
    return None


def _image(template: str | None) -> str | None:
    """Fill the `{recipe}` size placeholder in an ichef image URL."""
    return template.replace("{recipe}", IMAGE_SIZE) if template else None


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


def parse_broadcasts(data: dict[str, Any], now: datetime) -> Programme | None:
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
            image_url=_image(item.get("image_url")),
            logo_url=_logo(network.get("logo_url")),
        )
    return None


def parse_segments(data: dict[str, Any]) -> Track | None:
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
            image_url=_image(item.get("image_url")),
        )
    return None


def to_metadata(programme: Programme | None, track: Track | None) -> Metadata | None:
    """Choose what to show for a BBC station.

    Music: the track as title/artist, the programme as album. Talk: the
    programme as title, the station as artist, the episode subtitle as album.
    Art prefers the track image, then the programme image, then the logo.
    """
    if programme is None and track is None:
        return None
    station = programme.station if programme else None
    if track and track.title:
        title, artist = track.title, track.artist
        album = programme.title if programme else station
    else:
        assert programme is not None
        title, artist, album = programme.title, station, programme.subtitle
    image_url = next(
        (
            url
            for url in (
                track.image_url if track else None,
                programme.image_url if programme else None,
                programme.logo_url if programme else None,
            )
            if url
        ),
        None,
    )
    return Metadata(
        title=title or None,
        artist=artist or None,
        album=album or None,
        image_url=image_url,
        is_live=True,
    )


class BbcSoundsSource(MetadataSource):
    key = "bbc_sounds"
    name = "BBC Sounds"
    poll_interval = timedelta(seconds=20)

    def match(self, media_content_id: str | None) -> str | None:
        return service_id_from_uri(media_content_id)

    async def async_fetch(
        self, session: aiohttp.ClientSession, lookup_key: str
    ) -> Metadata | None:
        broadcasts, segments = await asyncio.gather(
            _get(session, f"broadcasts/poll/{lookup_key}"),
            _get(
                session,
                f"services/{lookup_key}/segments/latest",
                experience="domestic",
                offset="0",
                limit="1",
            ),
        )
        programme = parse_broadcasts(broadcasts, datetime.now(UTC)) if broadcasts else None
        track = parse_segments(segments) if segments else None
        return to_metadata(programme, track)


async def _get(
    session: aiohttp.ClientSession, path: str, **params: str
) -> dict[str, Any] | None:
    try:
        async with session.get(
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
