"""Sonos access via SoCo: speaker lookup, state snapshots, events and commands.

SoCo's network calls are synchronous, so they run in a worker thread. UPnP
events (via soco.events_asyncio) are only used as a trigger to take a fresh
snapshot; a periodic poll covers missed events and position updates.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import soco
from soco import SoCo
from soco import config as soco_config
from soco import events_asyncio

from .config import SonosConfig

_LOGGER = logging.getLogger(__name__)

SUBSCRIBED_SERVICES = ("avTransport", "renderingControl")


def configure_soco(cfg: SonosConfig) -> None:
    """Point SoCo at the asyncio event listener. Call before subscribing."""
    soco_config.EVENTS_MODULE = events_asyncio
    soco_config.EVENT_LISTENER_PORT = cfg.event_listener_port
    if cfg.advertise_ip:
        soco_config.EVENT_ADVERTISE_IP = cfg.advertise_ip


async def stop_event_listener() -> None:
    """Tear down SoCo's listener and HTTP session (idempotent)."""
    await events_asyncio.event_listener.async_stop()


def _hms_to_seconds(value: str | None) -> int | None:
    """Convert SoCo's 'H:MM:SS' strings to seconds ('NOT_IMPLEMENTED' → None)."""
    if not value or value == "NOT_IMPLEMENTED":
        return None
    try:
        h, m, s = (int(part) for part in value.split(":"))
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def seconds_to_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"


@dataclass(frozen=True)
class SonosSnapshot:
    """Everything the mux needs from one speaker, taken at one moment."""

    transport_state: str  # PLAYING, PAUSED_PLAYBACK, STOPPED, TRANSITIONING
    title: str
    artist: str
    album: str
    album_art: str
    track_uri: str
    media_uri: str
    channel: str
    position: int | None
    duration: int | None
    volume: int
    mute: bool
    music_source: str
    is_coordinator: bool

    @property
    def uris(self) -> tuple[str, ...]:
        return tuple(u for u in (self.track_uri, self.media_uri) if u)


def resolve_speaker(host: str | None, name: str | None) -> SoCo:
    """Find a speaker by IP/hostname, or by room name via SSDP discovery."""
    if host:
        return SoCo(host)
    assert name is not None
    speaker = soco.discovery.by_name(name)
    if speaker is None:
        raise LookupError(f"No Sonos speaker named {name!r} found on the network")
    return speaker


def take_snapshot(speaker: SoCo) -> SonosSnapshot:
    """Blocking: read track, transport and volume state for a speaker.

    Track and transport info come from the group coordinator, since grouped
    members report the coordinator's playback; volume and mute are per speaker.
    """
    coordinator = speaker.group.coordinator if speaker.group else speaker
    track = coordinator.get_current_track_info()
    transport = coordinator.get_current_transport_info()
    media = coordinator.get_current_media_info()
    return SonosSnapshot(
        transport_state=transport.get("current_transport_state", ""),
        title=track.get("title", ""),
        artist=track.get("artist", ""),
        album=track.get("album", ""),
        album_art=track.get("album_art", ""),
        track_uri=track.get("uri", ""),
        media_uri=media.get("uri", ""),
        channel=media.get("channel", ""),
        position=_hms_to_seconds(track.get("position")),
        duration=_hms_to_seconds(track.get("duration")),
        volume=speaker.volume,
        mute=speaker.mute,
        music_source=SoCo.music_source_from_uri(media.get("uri") or track.get("uri", "")),
        is_coordinator=coordinator is speaker,
    )


def raw_dump(speaker: SoCo) -> dict[str, Any]:
    """Blocking: unprocessed SoCo responses, for building test fixtures."""
    coordinator = speaker.group.coordinator if speaker.group else speaker
    track = coordinator.get_current_track_info()
    return {
        "player_name": speaker.player_name,
        "coordinator": coordinator.player_name,
        "track_info": track,
        "transport_info": coordinator.get_current_transport_info(),
        "media_info": coordinator.get_current_media_info(),
        "music_source": coordinator.music_source,
        "volume": speaker.volume,
        "mute": speaker.mute,
    }


class SonosPlayer:
    """One speaker: snapshots on demand, event subscription, and commands."""

    def __init__(self, speaker: SoCo):
        self.speaker = speaker
        self._subs: list[Any] = []

    @property
    def _coordinator(self) -> SoCo:
        return self.speaker.group.coordinator if self.speaker.group else self.speaker

    async def snapshot(self) -> SonosSnapshot:
        return await asyncio.to_thread(take_snapshot, self.speaker)

    async def subscribe(
        self,
        on_event: Callable[[str, dict[str, Any]], None],
        on_renew_fail: Callable[[Exception], Awaitable[None] | None],
    ) -> None:
        """Subscribe to UPnP events; `on_event(service, variables)` per event."""
        await self.unsubscribe()
        for name in SUBSCRIBED_SERVICES:
            service = getattr(self.speaker, name)
            sub = await service.subscribe(auto_renew=True)
            sub.callback = lambda event, name=name: on_event(name, event.variables)
            sub.auto_renew_fail = on_renew_fail
            self._subs.append(sub)
        _LOGGER.info("Subscribed to %s events", self.speaker.player_name)

    async def unsubscribe(self) -> None:
        subs, self._subs = self._subs, []
        for sub in subs:
            try:
                await sub.unsubscribe()
            except Exception as ex:  # noqa: BLE001 - speaker may already be gone
                _LOGGER.debug("Unsubscribe failed: %s", ex)

    # Commands. Transport goes to the group coordinator, volume to this speaker.

    async def play(self) -> None:
        await asyncio.to_thread(self._coordinator.play)

    async def pause(self) -> None:
        await asyncio.to_thread(self._coordinator.pause)

    async def next_track(self) -> None:
        await asyncio.to_thread(self._coordinator.next)

    async def previous_track(self) -> None:
        await asyncio.to_thread(self._coordinator.previous)

    async def seek(self, seconds: float) -> None:
        await asyncio.to_thread(self._coordinator.seek, seconds_to_hms(seconds))

    async def play_uri(self, uri: str) -> None:
        await asyncio.to_thread(self._coordinator.play_uri, uri)

    async def set_volume(self, level: float) -> None:
        volume = round(min(1.0, max(0.0, level)) * 100)
        await asyncio.to_thread(setattr, self.speaker, "volume", volume)

    async def set_mute(self, mute: bool) -> None:
        await asyncio.to_thread(setattr, self.speaker, "mute", mute)
