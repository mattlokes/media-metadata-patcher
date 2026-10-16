import re
from pathlib import Path

import pytest
from homeassistant.components.media_player import (
    DOMAIN as MP_DOMAIN,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.media_metadata_filler.const import CONF_SOURCES, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
WRAPPED = "media_player.kitchen"
FILLED = "media_player.kitchen_filled"
BBC_URI = "hls-radio://https://a.files.bbci.co.uk/ms6/live/x/audio/simulcast/hls/uk/voice_sbr_v1/aks/bbc_radio_two.m3u8"

AMAZON_ATTRS = {
    "friendly_name": "Kitchen",
    "supported_features": 4127295,
    "volume_level": 0.12,
    "is_volume_muted": False,
    "media_content_id": "https://d2qhcol036tlr5.cloudfront.net/api/manifest.m3u8?dmid=202987900",
    "media_content_type": "music",
    "media_title": "Hungry Like The Wolf (2001 Remastered Version)",
    "media_artist": "Duran Duran",
    "media_album_name": "Rio",
    "media_duration": 221,
    "media_position": 12,
    "entity_picture": "/api/media_player_proxy/media_player.kitchen?token=abc",
}
BBC_ATTRS = {
    "friendly_name": "Kitchen",
    "supported_features": 4127295,
    "volume_level": 0.12,
    "is_volume_muted": False,
    "media_content_id": BBC_URI,
    "media_content_type": "music",
    "media_title": None,
    "entity_picture": "/api/media_player_proxy/media_player.kitchen?token=generic",
}


@pytest.fixture
def bbc_api(aioclient_mock, freezer):
    freezer.move_to("2026-10-16T15:30:00+00:00")
    aioclient_mock.get(
        "https://rms.api.bbc.co.uk/v2/broadcasts/poll/bbc_radio_two",
        text=(FIXTURES / "bbc_broadcasts_radio_two.json").read_text(),
    )
    aioclient_mock.get(
        re.compile(r"/v2/services/bbc_radio_two/segments/latest"),
        text=(FIXTURES / "bbc_segments_music.json").read_text(),
    )
    return aioclient_mock


async def _setup(hass, wrapped=WRAPPED, sources=("bbc_sounds",)):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=wrapped,
        title="Kitchen filled",
        options={CONF_ENTITY_ID: wrapped, CONF_SOURCES: list(sources)},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_passes_through_non_bbc(hass):
    hass.states.async_set(WRAPPED, "playing", AMAZON_ATTRS)
    await _setup(hass)
    state = hass.states.get(FILLED)
    assert state.state == "playing"
    assert state.attributes["media_title"] == AMAZON_ATTRS["media_title"]
    assert state.attributes["media_artist"] == "Duran Duran"
    assert state.attributes["media_album_name"] == "Rio"
    assert state.attributes["media_duration"] == 221
    assert state.attributes["volume_level"] == 0.12
    assert state.attributes["entity_picture"] == AMAZON_ATTRS["entity_picture"]
    assert state.attributes["wrapped_entity_id"] == WRAPPED
    assert state.attributes["filled_by"] is None


async def test_fills_bbc_stream(hass, bbc_api):
    hass.states.async_set(WRAPPED, "playing", BBC_ATTRS)
    await _setup(hass)
    state = hass.states.get(FILLED)
    assert state.attributes["media_title"] == "The Reflex"
    assert state.attributes["media_artist"] == "Duran Duran"
    assert state.attributes["media_album_name"] == "Radio 2 Drivetime"
    assert state.attributes["entity_picture"] == "https://ichef.bbci.co.uk/images/ic/640x640/p05b8vz5.jpg"
    assert "media_duration" not in state.attributes
    assert state.attributes["filled_by"] == "bbc_sounds"


async def test_switching_streams_and_stopping(hass, bbc_api):
    hass.states.async_set(WRAPPED, "playing", AMAZON_ATTRS)
    await _setup(hass)
    hass.states.async_set(WRAPPED, "playing", BBC_ATTRS)
    await hass.async_block_till_done()
    assert hass.states.get(FILLED).attributes["media_title"] == "The Reflex"

    # A stopped player keeps its BBC media_content_id; don't show stale BBC data.
    hass.states.async_set(WRAPPED, "idle", BBC_ATTRS)
    await hass.async_block_till_done()
    state = hass.states.get(FILLED)
    assert state.state == "idle"
    assert state.attributes.get("filled_by") is None
    assert "media_title" not in state.attributes


async def test_source_disabled(hass, bbc_api):
    hass.states.async_set(WRAPPED, "playing", BBC_ATTRS)
    await _setup(hass, sources=())
    assert hass.states.get(FILLED).attributes["filled_by"] is None
    assert bbc_api.call_count == 0


async def test_bbc_api_down_falls_back(hass, aioclient_mock):
    aioclient_mock.get(re.compile(r"rms\.api\.bbc\.co\.uk"), status=503)
    hass.states.async_set(WRAPPED, "playing", BBC_ATTRS)
    await _setup(hass)
    state = hass.states.get(FILLED)
    assert state.state == "playing"
    assert state.attributes["entity_picture"] == BBC_ATTRS["entity_picture"]


async def test_unavailable_when_wrapped_missing(hass):
    await _setup(hass)
    assert hass.states.get(FILLED).state == "unavailable"


class FakePlayer(MediaPlayerEntity):
    """A minimal real media player, so forwarded service calls can be observed."""

    _attr_name = "Walkman"
    _attr_unique_id = "fake_walkman"
    _attr_state = MediaPlayerState.PLAYING
    _attr_volume_level = 0.5
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.NEXT_TRACK
    )

    def __init__(self):
        self.calls = []

    async def async_media_pause(self):
        self.calls.append("pause")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        self.calls.append(("volume", volume))
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_media_next_track(self):
        self.calls.append("next")


async def test_commands_forward_to_wrapped_player(hass):
    assert await async_setup_component(hass, MP_DOMAIN, {})
    fake = FakePlayer()
    await hass.data[MP_DOMAIN].async_add_entities([fake])
    walkman = "media_player.walkman"
    await _setup(hass, wrapped=walkman)
    assert hass.states.get(FILLED).state == "playing"
    assert hass.states.get(FILLED).attributes["supported_features"] == fake.supported_features

    await hass.services.async_call(MP_DOMAIN, "media_pause", {ATTR_ENTITY_ID: FILLED}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(walkman).state == "paused"
    assert hass.states.get(FILLED).state == "paused"

    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: FILLED, "volume_level": 0.3}, blocking=True
    )
    await hass.services.async_call(MP_DOMAIN, "media_next_track", {ATTR_ENTITY_ID: FILLED}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(FILLED).attributes["volume_level"] == 0.3
    assert fake.calls == ["pause", ("volume", 0.3), "next"]
