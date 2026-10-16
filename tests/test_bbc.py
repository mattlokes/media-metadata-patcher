import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hass_sonos_metadata_mux.bbc import parse_broadcasts, parse_segments, service_id_from_uris

FIXTURES = Path(__file__).parent / "fixtures"

# URIs as a Kitchen Sonos One reported them when Alexa started BBC Sounds
# (jwt_auth token removed).
BBC_MEDIA_URI = (
    "x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/6/redir/version/2.0"
    "/vpid/bbc_radio_two/mediaset/voice-hls/proto/https?jwt_auth=REDACTED"
)
BBC_TRACK_URI = (
    "hls-radio://https://a.files.bbci.co.uk/ms6/live/3441A116-B12E-4D2F-ACA8-C1984642FA4B"
    "/audio/simulcast/hls/uk/voice_sbr_v1/aks/bbc_radio_two.m3u8"
)


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    ("uris", "expected"),
    [
        ((BBC_MEDIA_URI,), "bbc_radio_two"),
        ((BBC_TRACK_URI,), "bbc_radio_two"),
        (("", BBC_MEDIA_URI.replace("bbc_radio_two", "bbc_6music")), "bbc_6music"),
        (("x-rincon-mp3radio://https://media-ssl.musicradio.com/SmoothHertsMP3",), None),
        (("https://d2qhcol036tlr5.cloudfront.net/api/manifest.m3u8?dmid=1",), None),
        ((), None),
    ],
)
def test_service_id_from_uris(uris, expected):
    assert service_id_from_uris(uris) == expected


def test_parse_broadcasts_picks_programme_on_air():
    data = _load("bbc_broadcasts_radio_two.json")
    drivetime = parse_broadcasts(data, datetime(2026, 10, 16, 15, 30, tzinfo=UTC), "640x640")
    assert drivetime.station == "Radio 2"
    assert drivetime.title == "Radio 2 Drivetime"
    assert drivetime.subtitle == "All Request Friday"
    assert drivetime.image_url == "https://ichef.bbci.co.uk/images/ic/640x640/p0nph33g.jpg"
    assert drivetime.logo_url.endswith("/bbc_radio_two/blocks-colour_600x600.png")

    evening = parse_broadcasts(data, datetime(2026, 10, 16, 18, 0, tzinfo=UTC), "640x640")
    assert evening.title == "Michelle Visage"

    assert parse_broadcasts(data, datetime(2026, 10, 17, 9, 0, tzinfo=UTC), "640x640") is None


def test_parse_segments_music():
    track = parse_segments(_load("bbc_segments_music.json"), "640x640")
    assert (track.artist, track.title) == ("Duran Duran", "The Reflex")
    assert track.image_url == "https://ichef.bbci.co.uk/images/ic/640x640/p05b8vz5.jpg"


def test_parse_segments_talk_and_finished_track():
    assert parse_segments(_load("bbc_segments_talk.json"), "640x640") is None
    finished = _load("bbc_segments_music.json")
    finished["data"][0]["offset"]["now_playing"] = False
    assert parse_segments(finished, "640x640") is None
