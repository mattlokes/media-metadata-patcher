# hass-sonos-metadata-mux

When a Sonos speaker plays a BBC Sounds live station (for example after
"Alexa, play Radio 2 on BBC Sounds"), Sonos reports no title, artist or
artwork, so Home Assistant's Sonos entity shows nothing. Other services
(Amazon Music, Apple Music, TuneIn, Global Player) report metadata fine.

The stream URI does name the BBC service (e.g. `bbc_radio_two`), and BBC's own
now-playing API knows the current track, programme and artwork. This service:

- watches and controls the Sonos speaker directly with [SoCo](https://github.com/SoCo/SoCo)
- for BBC streams, fills in metadata from the BBC (track when music is playing,
  otherwise the programme), and passes everything else through from the Sonos
- publishes one `media_player` per speaker to Home Assistant over MQTT, using the
  [mqtt_media_player](https://github.com/bkbilly/hass-mqtt-mediaplayer) HACS integration

> Status: early development. The BBC endpoint (`rms.api.bbc.co.uk`) is the one
> the BBC Sounds web app uses; it is unofficial and could change.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- This machine on the same LAN as the Sonos speakers (they push UPnP events to it)
- For Home Assistant: an MQTT broker (e.g. the Mosquitto add-on) and the
  `mqtt_media_player` integration from HACS

## Quick start (development)

```sh
uv sync
cp config.example.toml config.toml   # edit it
uv run hass-sonos-metadata-mux preview --player kitchen            # merged metadata now
uv run hass-sonos-metadata-mux preview --player kitchen --watch 300
uv run hass-sonos-metadata-mux bbc bbc_6music                      # BBC lookup only
uv run hass-sonos-metadata-mux sonos-dump --player kitchen         # raw Sonos state
uv run pytest
```

## License

MIT
