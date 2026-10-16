# hass-sonos-metadata-mux

When a Sonos speaker with Alexa built-in plays something started by voice
(e.g. "Alexa, play Radio 6 on BBC Sounds"), Sonos doesn't publish the
now-playing title or artwork locally, so Home Assistant's Sonos entity shows
nothing. Amazon does have that data.

This service runs alongside Home Assistant (e.g. in a Proxmox LXC) and:

- watches and controls the Sonos speaker directly with [SoCo](https://github.com/SoCo/SoCo)
- reads Alexa now-playing metadata via [alexapy](https://gitlab.com/keatontaylor/alexapy)
- publishes one merged `media_player` per speaker to Home Assistant over MQTT,
  using the [mqtt_media_player](https://github.com/bkbilly/hass-mqtt-mediaplayer) HACS integration

> Status: early development. Uses Amazon's **unofficial** API, which can change without notice.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- An MQTT broker reachable by Home Assistant (e.g. the Mosquitto add-on)
- The `mqtt_media_player` integration installed from HACS
- This machine on the same LAN as the Sonos speakers (they push UPnP events to it)

## Quick start (development)

```sh
uv sync
cp config.example.toml config.toml   # edit it
uv run hass-sonos-metadata-mux --config config.toml enroll       # one-time Amazon login
uv run hass-sonos-metadata-mux --config config.toml alexa-devices
uv run hass-sonos-metadata-mux --config config.toml sonos-dump
uv run hass-sonos-metadata-mux --config config.toml alexa-dump
```

## License

MIT
