from dataclasses import replace

from hass_sonos_metadata_mux.bbc import BbcNowPlaying, Programme, Track
from hass_sonos_metadata_mux.mux import mux
from hass_sonos_metadata_mux.sonos import SonosSnapshot

# What the Sonos reported for Amazon Music started via Alexa.
AMAZON_MUSIC = SonosSnapshot(
    transport_state="PLAYING",
    title="Hungry Like The Wolf (2001 Remastered Version)",
    artist="Duran Duran",
    album="Rio",
    album_art="https://m.media-amazon.com/images/I/712XJif-X-L._UL600_.jpg",
    track_uri="https://d2qhcol036tlr5.cloudfront.net/api/manifest.m3u8?dmid=202987900",
    media_uri="x-rincon-queue:RINCON_000000000000001400#4",
    channel="",
    position=12,
    duration=221,
    volume=12,
    mute=False,
    music_source="LIBRARY",
    is_coordinator=True,
)

# What the Sonos reported for BBC Sounds started via Alexa: no metadata at all.
BBC_STREAM = replace(
    AMAZON_MUSIC,
    title="",
    artist="",
    album="",
    album_art="",
    track_uri="hls-radio://https://a.files.bbci.co.uk/x/bbc_radio_two.m3u8",
    media_uri="x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/6/vpid/bbc_radio_two/x",
    channel=" ",
    position=48,
    duration=None,
    music_source="RADIO",
)

DRIVETIME = Programme(
    station="Radio 2",
    title="Radio 2 Drivetime",
    subtitle="All Request Friday",
    image_url="https://ichef.bbci.co.uk/images/ic/640x640/programme.jpg",
    logo_url="https://sounds.files.bbci.co.uk/logo.png",
)
REFLEX = Track("Duran Duran", "The Reflex", "https://ichef.bbci.co.uk/images/ic/640x640/track.jpg")


def test_non_bbc_passes_sonos_through():
    out = mux(AMAZON_MUSIC, None)
    assert (out.title, out.artist, out.album) == (AMAZON_MUSIC.title, "Duran Duran", "Rio")
    assert out.image_url == AMAZON_MUSIC.album_art
    assert (out.state, out.position, out.duration, out.volume) == ("playing", 12, 221, 0.12)
    assert out.source == "sonos"


def test_bbc_music_track():
    out = mux(BBC_STREAM, BbcNowPlaying("bbc_radio_two", DRIVETIME, REFLEX))
    assert (out.title, out.artist, out.album) == ("The Reflex", "Duran Duran", "Radio 2 Drivetime")
    assert out.image_url == REFLEX.image_url
    assert (out.duration, out.position, out.source) == (None, None, "bbc")


def test_bbc_talk_uses_programme():
    out = mux(BBC_STREAM, BbcNowPlaying("bbc_radio_two", DRIVETIME, None))
    assert (out.title, out.artist, out.album) == (
        "Radio 2 Drivetime",
        "Radio 2",
        "All Request Friday",
    )
    assert out.image_url == DRIVETIME.image_url


def test_bbc_art_falls_back_to_logo():
    programme = replace(DRIVETIME, image_url=None)
    track = replace(REFLEX, image_url=None)
    out = mux(BBC_STREAM, BbcNowPlaying("bbc_radio_two", programme, track))
    assert out.image_url == DRIVETIME.logo_url


def test_bbc_api_unavailable_shows_service_id():
    out = mux(BBC_STREAM, BbcNowPlaying("bbc_radio_two", None, None))
    assert out.title == "bbc_radio_two"
    assert out.image_url is None


def test_stopped_speaker_ignores_stale_bbc():
    stopped = replace(BBC_STREAM, transport_state="STOPPED")
    out = mux(stopped, BbcNowPlaying("bbc_radio_two", DRIVETIME, REFLEX))
    assert out.state == "idle"
    assert out.source == "sonos"
    assert out.title == ""


def test_paused_state():
    assert mux(replace(AMAZON_MUSIC, transport_state="PAUSED_PLAYBACK"), None).state == "paused"
