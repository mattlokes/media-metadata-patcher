from pathlib import Path

import pytest

from hass_sonos_metadata_mux.config import ConfigError, parse_config


def _player(**overrides):
    return {"id": "kitchen", "sonos_host": "10.0.0.2", **overrides}


def test_defaults(tmp_path: Path):
    cfg = parse_config({"player": [_player()]}, tmp_path)
    assert cfg.mqtt is None
    assert cfg.bbc.image_size == "640x640"
    assert cfg.players[0].name == "kitchen"


def test_password_file_is_read(tmp_path: Path):
    (tmp_path / "pw").write_text("secret\n")
    cfg = parse_config({"mqtt": {"host": "broker", "password_file": "pw"}}, tmp_path)
    assert cfg.mqtt.password == "secret"


@pytest.mark.parametrize(
    ("player", "message"),
    [
        ({"id": "Bad-Id", "sonos_host": "x"}, "lowercase"),
        ({"id": "kitchen"}, "sonos_host or sonos_name"),
    ],
)
def test_invalid_players(tmp_path: Path, player, message):
    with pytest.raises(ConfigError, match=message):
        parse_config({"player": [player]}, tmp_path)


def test_duplicate_ids(tmp_path: Path):
    with pytest.raises(ConfigError, match="unique"):
        parse_config({"player": [_player(), _player()]}, tmp_path)
