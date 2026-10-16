"""Overlay source metadata on a wrapped media player's own attributes.

Pure functions, so the rules can be tested without Home Assistant running.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .sources.base import Metadata

# Wrapped-player states in which source metadata may apply. A stopped player
# keeps its last media_content_id, so idle/off must not show stale data.
ACTIVE_STATES = frozenset({"playing", "paused", "buffering"})


@dataclass(frozen=True)
class PatchedMedia:
    title: str | None
    artist: str | None
    album: str | None
    image_url: str | None
    duration: float | None
    position: float | None
    position_updated_at: datetime | None
    patched: bool


def is_active(state: str | None) -> bool:
    return state in ACTIVE_STATES


def patch_media(state: str | None, attrs: Mapping[str, Any], metadata: Metadata | None) -> PatchedMedia:
    """Return what the wrapper should show.

    With no metadata (no match, nothing fetched yet, or player not active) the
    wrapped player's values pass through, including its already-proxied
    `entity_picture`. Otherwise each non-None metadata field replaces the
    player's value, and live streams drop duration and position.
    """
    own = PatchedMedia(
        title=attrs.get("media_title"),
        artist=attrs.get("media_artist"),
        album=attrs.get("media_album_name"),
        image_url=attrs.get("entity_picture"),
        duration=attrs.get("media_duration"),
        position=attrs.get("media_position"),
        position_updated_at=attrs.get("media_position_updated_at"),
        patched=False,
    )
    if metadata is None or not is_active(state):
        return own
    return PatchedMedia(
        title=metadata.title if metadata.title is not None else own.title,
        artist=metadata.artist if metadata.artist is not None else own.artist,
        album=metadata.album if metadata.album is not None else own.album,
        image_url=metadata.image_url if metadata.image_url is not None else own.image_url,
        duration=None if metadata.is_live else own.duration,
        position=None if metadata.is_live else own.position,
        position_updated_at=None if metadata.is_live else own.position_updated_at,
        patched=True,
    )
