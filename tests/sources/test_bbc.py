import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.media_metadata_filler.sources.bbc import (
    BbcSoundsSource,
    Programme,
    Track,
    parse_broadcasts,
    parse_segments,
    service_id_from_uri,
    to_metadata,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"

# URIs a Sonos reported when Alexa started BBC Sounds (jwt_auth token removed).
# HA's Sonos entity exposes the second one as media_content_id.
BBC_MEDIA_URI = (
    "x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/6/redir/version/2.0"
    "/vpid/bbc_radio_two/mediaset/voice-hls/proto/https?jwt_auth=REDACTED"
)
BBC_TRACK_URI = (
    "hls-radio://https://a.files.bbci.co.uk/ms6/live/3441A116-B12E-4D2F-ACA8-C1984642FA4B"
    "/audio/simulcast/hls/uk/voice_sbr_v1/aks/bbc_radio_two.m3u8"
)

DRIVETIME = Programme(
    station="Radio 2",
    title="Radio 2 Drivetime",
    subtitle="All Request Friday",
    image_url="https://ichef.bbci.co.uk/images/ic/640x640/programme.jpg",
    logo_url="https://sounds.files.bbci.co.uk/logo.png",
)
REFLEX = Track("Duran Duran", "The Reflex", "https://ichef.bbci.co.uk/images/ic/640x640/track.jpg")


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (BBC_MEDIA_URI, "bbc_radio_two"),
        (BBC_TRACK_URI, "bbc_radio_two"),
        (BBC_TRACK_URI.replace("bbc_radio_two", "bbc_6music"), "bbc_6music"),
        ("x-rincon-mp3radio://https://media-ssl.musicradio.com/SmoothHertsMP3", None),
        ("https://d2qhcol036tlr5.cloudfront.net/api/manifest.m3u8?dmid=1", None),
        ("", None),
        (None, None),
    ],
)
def test_service_id_from_uri(uri, expected):
    assert service_id_from_uri(uri) == expected
    assert BbcSoundsSource().match(uri) == expected


def test_parse_broadcasts_picks_programme_on_air():
    data = _load("bbc_broadcasts_radio_two.json")
    drivetime = parse_broadcasts(data, datetime(2026, 10, 16, 15, 30, tzinfo=UTC))
    assert drivetime.station == "Radio 2"
    assert drivetime.title == "Radio 2 Drivetime"
    assert drivetime.subtitle == "All Request Friday"
    assert drivetime.image_url == "https://ichef.bbci.co.uk/images/ic/640x640/p0nph33g.jpg"
    assert drivetime.logo_url.endswith("/bbc_radio_two/blocks-colour_600x600.png")

    evening = parse_broadcasts(data, datetime(2026, 10, 16, 18, 0, tzinfo=UTC))
    assert evening.title == "Michelle Visage"

    assert parse_broadcasts(data, datetime(2026, 10, 17, 9, 0, tzinfo=UTC)) is None


def test_parse_segments_music():
    track = parse_segments(_load("bbc_segments_music.json"))
    assert (track.artist, track.title) == ("Duran Duran", "The Reflex")
    assert track.image_url == "https://ichef.bbci.co.uk/images/ic/640x640/p05b8vz5.jpg"


def test_parse_segments_talk_and_finished_track():
    assert parse_segments(_load("bbc_segments_talk.json")) is None
    finished = _load("bbc_segments_music.json")
    finished["data"][0]["offset"]["now_playing"] = False
    assert parse_segments(finished) is None


def test_music_track_shows_song_with_programme_as_album():
    meta = to_metadata(DRIVETIME, REFLEX)
    assert (meta.title, meta.artist, meta.album) == ("The Reflex", "Duran Duran", "Radio 2 Drivetime")
    assert meta.image_url == REFLEX.image_url
    assert meta.is_live


def test_talk_shows_programme():
    meta = to_metadata(DRIVETIME, None)
    assert (meta.title, meta.artist, meta.album) == ("Radio 2 Drivetime", "Radio 2", "All Request Friday")
    assert meta.image_url == DRIVETIME.image_url


def test_art_falls_back_to_logo():
    meta = to_metadata(
        Programme("Radio 2", "Drivetime", "", None, "https://logo"),
        Track("Duran Duran", "The Reflex", None),
    )
    assert meta.image_url == "https://logo"


def test_track_without_programme():
    meta = to_metadata(None, REFLEX)
    assert (meta.title, meta.artist, meta.album) == ("The Reflex", "Duran Duran", None)


def test_nothing_known():
    assert to_metadata(None, None) is None


async def test_async_fetch(hass, aioclient_mock, freezer):
    freezer.move_to("2026-10-16T15:30:00+00:00")
    aioclient_mock.get(
        "https://rms.api.bbc.co.uk/v2/broadcasts/poll/bbc_radio_two",
        text=(FIXTURES / "bbc_broadcasts_radio_two.json").read_text(),
    )
    aioclient_mock.get(
        re.compile(r"/v2/services/bbc_radio_two/segments/latest"),
        text=(FIXTURES / "bbc_segments_music.json").read_text(),
    )
    meta = await BbcSoundsSource().async_fetch(async_get_clientsession(hass), "bbc_radio_two")
    assert (meta.title, meta.artist, meta.album) == ("The Reflex", "Duran Duran", "Radio 2 Drivetime")


async def test_async_fetch_api_down(hass, aioclient_mock):
    aioclient_mock.get(re.compile(r"rms\.api\.bbc\.co\.uk"), status=503)
    assert await BbcSoundsSource().async_fetch(async_get_clientsession(hass), "bbc_radio_two") is None
