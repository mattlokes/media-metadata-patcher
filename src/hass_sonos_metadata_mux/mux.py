"""Combine Sonos state with BBC now-playing into what the HA entity shows.

Pure functions only, so the rules can be tested against recorded fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bbc import BbcNowPlaying
from .sonos import SonosSnapshot

# Sonos transport states → mqtt_media_player states.
_STATES = {
    "PLAYING": "playing",
    "TRANSITIONING": "playing",
    "PAUSED_PLAYBACK": "paused",
    "STOPPED": "idle",
}


@dataclass(frozen=True)
class MuxedState:
    state: str
    title: str
    artist: str
    album: str
    image_url: str | None
    duration: int | None
    position: int | None
    volume: float
    muted: bool
    source: str  # "sonos" or "bbc", for logging and diagnostics


def mux(sonos: SonosSnapshot, bbc: BbcNowPlaying | None) -> MuxedState:
    """Sonos is authoritative for playback; BBC fills metadata for BBC streams.

    For a BBC stream, a music track (when one is flagged now playing) gives the
    title and artist, and the programme supplies the album line. During talk,
    the programme becomes the title and the station the artist. Art prefers
    track, then programme, then station logo. Live radio has no duration.
    """
    state = _STATES.get(sonos.transport_state, "idle")
    volume = sonos.volume / 100
    # A stopped speaker keeps its last URI; don't present stale BBC metadata.
    if bbc is None or state == "idle":
        return MuxedState(
            state=state,
            title=sonos.title,
            artist=sonos.artist,
            album=sonos.album,
            image_url=sonos.album_art or None,
            duration=sonos.duration or None,
            position=sonos.position if sonos.duration else None,
            volume=volume,
            muted=sonos.mute,
            source="sonos",
        )

    programme, track = bbc.programme, bbc.track
    station = programme.station if programme else ""
    if track and track.title:
        title, artist = track.title, track.artist
        album = programme.title if programme else station
    elif programme:
        title, artist, album = programme.title, station, programme.subtitle
    else:
        title, artist, album = sonos.title or bbc.service_id, sonos.artist, sonos.album

    image_url = next(
        (
            url
            for url in (
                track.image_url if track else None,
                programme.image_url if programme else None,
                programme.logo_url if programme else None,
                sonos.album_art or None,
            )
            if url
        ),
        None,
    )
    return MuxedState(
        state=state,
        title=title,
        artist=artist,
        album=album,
        image_url=image_url,
        duration=None,
        position=None,
        volume=volume,
        muted=sonos.mute,
        source="bbc",
    )
