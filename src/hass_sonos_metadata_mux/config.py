"""TOML configuration loading.

Relative paths in the config are resolved against the config file's directory,
so the same layout works on a dev machine and in the LXC.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "hass_sonos_metadata_mux"

_ID_RE = re.compile(r"^[a-z0-9_]+$")

# Sonos uses x-sonos-vli: ("voice line-in") URIs for AirPlay and Spotify Connect
# as well as Alexa, so match vli URIs that are neither. Confirm against a real
# Alexa dump (`sonos-dump`) and override per player if needed.
DEFAULT_ALEXA_URI_PATTERNS = (r"^x-sonos-vli:(?!.*,(?:airplay|spotify):)",)


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    discovery_prefix: str = "homeassistant"
    base_topic: str = APP_NAME


@dataclass(frozen=True)
class SonosConfig:
    event_listener_port: int = 1400
    advertise_ip: str | None = None


@dataclass(frozen=True)
class AlexaConfig:
    domain: str = "amazon.com"
    poll_interval: float = 15.0


@dataclass(frozen=True)
class PlayerConfig:
    id: str
    name: str
    sonos_host: str | None = None
    sonos_name: str | None = None
    alexa_device: str | None = None
    alexa_uri_patterns: tuple[re.Pattern[str], ...] = tuple(
        re.compile(p) for p in DEFAULT_ALEXA_URI_PATTERNS
    )


@dataclass(frozen=True)
class Config:
    state_dir: Path
    mqtt: MqttConfig | None
    sonos: SonosConfig
    alexa: AlexaConfig
    players: tuple[PlayerConfig, ...] = field(default_factory=tuple)

    @property
    def alexa_credentials_file(self) -> Path:
        return self.state_dir / "alexa_credentials.json"

    @property
    def enroll_state_file(self) -> Path:
        return self.state_dir / "enroll_state.json"


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _read_secret(base: Path, section: dict[str, Any], key: str) -> str | None:
    """Return `key` directly, or the contents of the file named by `key_file`."""
    if key in section:
        return str(section[key])
    file_key = f"{key}_file"
    if file_key in section:
        path = _resolve(base, section[file_key])
        try:
            return path.read_text().strip()
        except OSError as ex:
            raise ConfigError(f"Cannot read {file_key} {path}: {ex}") from ex
    return None


def _player(raw: dict[str, Any]) -> PlayerConfig:
    try:
        player_id = str(raw["id"])
    except KeyError as ex:
        raise ConfigError("Every [[player]] needs an id") from ex
    if not _ID_RE.match(player_id):
        raise ConfigError(
            f"player id {player_id!r} must be lowercase letters, digits or _"
        )
    if not (raw.get("sonos_host") or raw.get("sonos_name")):
        raise ConfigError(f"player {player_id!r} needs sonos_host or sonos_name")
    try:
        patterns = tuple(
            re.compile(str(p))
            for p in raw.get("alexa_uri_patterns", DEFAULT_ALEXA_URI_PATTERNS)
        )
    except re.error as ex:
        raise ConfigError(f"player {player_id!r} has an invalid pattern: {ex}") from ex
    return PlayerConfig(
        id=player_id,
        name=str(raw.get("name", player_id)),
        sonos_host=raw.get("sonos_host"),
        sonos_name=raw.get("sonos_name"),
        alexa_device=raw.get("alexa_device"),
        alexa_uri_patterns=patterns,
    )


def parse_config(data: dict[str, Any], base: Path) -> Config:
    mqtt_raw = data.get("mqtt")
    mqtt = None
    if mqtt_raw is not None:
        if "host" not in mqtt_raw:
            raise ConfigError("[mqtt] needs a host")
        mqtt = MqttConfig(
            host=str(mqtt_raw["host"]),
            port=int(mqtt_raw.get("port", 1883)),
            username=mqtt_raw.get("username"),
            password=_read_secret(base, mqtt_raw, "password"),
            discovery_prefix=str(mqtt_raw.get("discovery_prefix", "homeassistant")),
            base_topic=str(mqtt_raw.get("base_topic", APP_NAME)),
        )

    sonos_raw = data.get("sonos", {})
    sonos = SonosConfig(
        event_listener_port=int(sonos_raw.get("event_listener_port", 1400)),
        advertise_ip=sonos_raw.get("advertise_ip"),
    )

    alexa_raw = data.get("alexa", {})
    alexa = AlexaConfig(
        domain=str(alexa_raw.get("domain", "amazon.com")),
        poll_interval=float(alexa_raw.get("poll_interval", 15)),
    )

    players = tuple(_player(p) for p in data.get("player", []))
    ids = [p.id for p in players]
    if len(ids) != len(set(ids)):
        raise ConfigError("player ids must be unique")

    return Config(
        state_dir=_resolve(base, data.get("state_dir", ".state")),
        mqtt=mqtt,
        sonos=sonos,
        alexa=alexa,
        players=players,
    )


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as ex:
        raise ConfigError(f"Config file not found: {path}") from ex
    except tomllib.TOMLDecodeError as ex:
        raise ConfigError(f"Invalid TOML in {path}: {ex}") from ex
    return parse_config(data, path.resolve().parent)
