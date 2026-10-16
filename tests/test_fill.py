from custom_components.media_metadata_filler.fill import fill
from custom_components.media_metadata_filler.sources import Metadata

ATTRS = {
    "media_title": "Own title",
    "media_artist": "Own artist",
    "media_album_name": "Own album",
    "entity_picture": "/api/media_player_proxy/media_player.kitchen?token=x",
    "media_duration": 221,
    "media_position": 12,
    "media_position_updated_at": "2026-10-16T15:30:00+00:00",
}


def test_no_metadata_passes_through():
    out = fill("playing", ATTRS, None)
    assert (out.title, out.artist, out.album) == ("Own title", "Own artist", "Own album")
    assert out.image_url == ATTRS["entity_picture"]
    assert (out.duration, out.position) == (221, 12)
    assert not out.filled


def test_full_metadata_replaces_and_live_clears_position():
    meta = Metadata("T", "A", "B", "https://img", is_live=True)
    out = fill("playing", ATTRS, meta)
    assert (out.title, out.artist, out.album, out.image_url) == ("T", "A", "B", "https://img")
    assert (out.duration, out.position, out.position_updated_at) == (None, None, None)
    assert out.filled


def test_partial_metadata_keeps_own_fields():
    out = fill("paused", ATTRS, Metadata(image_url="https://img"))
    assert (out.title, out.artist, out.album) == ("Own title", "Own artist", "Own album")
    assert out.image_url == "https://img"
    assert (out.duration, out.position) == (221, 12)


def test_inactive_player_ignores_metadata():
    for state in ("idle", "off", "on", None):
        assert not fill(state, ATTRS, Metadata("T")).filled
