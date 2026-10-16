from pathlib import Path

import pytest

from hass_sonos_metadata_mux.config import ConfigError, parse_config


def _player(**overrides):
    return {"id": "kitchen", "sonos_host": "10.0.0.2", **overrides}


def test_defaults_and_relative_state_dir(tmp_path: Path):
    cfg = parse_config({"player": [_player()]}, tmp_path)
    assert cfg.state_dir == tmp_path / ".state"
    assert cfg.mqtt is None
    assert cfg.alexa.domain == "amazon.com"
    assert cfg.players[0].name == "kitchen"


def test_password_file_is_read(tmp_path: Path):
    (tmp_path / "pw").write_text("secret\n")
    cfg = parse_config({"mqtt": {"host": "broker", "password_file": "pw"}}, tmp_path)
    assert cfg.mqtt.password == "secret"


@pytest.mark.parametrize(
    ("uri", "is_alexa"),
    [
        ("x-sonos-vli:RINCON_ABC01400:1,airplay:1234", False),
        ("x-sonos-vli:RINCON_ABC01400:1,spotify:1234", False),
        ("x-sonos-vli:RINCON_ABC01400:2,alexa:1234", True),
        ("x-sonos-http:librarytrack%3a123.mp4", False),
        ("", False),
    ],
)
def test_default_alexa_pattern(tmp_path: Path, uri: str, is_alexa: bool):
    player = parse_config({"player": [_player()]}, tmp_path).players[0]
    assert any(p.search(uri) for p in player.alexa_uri_patterns) is is_alexa


@pytest.mark.parametrize(
    ("player", "message"),
    [
        ({"id": "Bad-Id", "sonos_host": "x"}, "lowercase"),
        ({"id": "kitchen"}, "sonos_host or sonos_name"),
        (_player(alexa_uri_patterns=["("]), "invalid pattern"),
    ],
)
def test_invalid_players(tmp_path: Path, player, message):
    with pytest.raises(ConfigError, match=message):
        parse_config({"player": [player]}, tmp_path)


def test_duplicate_ids(tmp_path: Path):
    with pytest.raises(ConfigError, match="unique"):
        parse_config({"player": [_player(), _player()]}, tmp_path)
