# Media Metadata Patcher

A Home Assistant integration that fills in missing now-playing metadata
(title, artist, album, artwork) on any `media_player`.

Some streams arrive at a player with no metadata at all. The motivating case:
a Sonos speaker playing a **BBC Sounds** live station (for example after
"Alexa, play Radio 2 on BBC Sounds") reports nothing but a playlist filename,
so Home Assistant shows a blank player. Other services on the same speaker
(Amazon Music, Apple Music, TuneIn, Global Player) report metadata fine. See
[docs/sonos-stream-metadata.md](docs/sonos-stream-metadata.md) for what was
measured.

## How it works

For each media player you choose, the integration creates a new media player
entity that:

- **mirrors** the original: state, volume, source, grouping, supported
  features, and everything else
- **forwards every command** (play, pause, volume, play media, browse, join…)
  to the original, so control works exactly as before
- **fills in metadata** when a source recognises the stream from its
  `media_content_id`. Anything a source doesn't provide passes through.

The new entity is attached to the same device as the original. You'll
probably want to hide the original entity and use the patched one on
dashboards.

Extra attributes: `wrapped_entity_id`, and `patched_by` (the source key while
metadata is being patched, otherwise `null`).

## Sources

| Source | Recognises | Provides |
|---|---|---|
| BBC Sounds (`bbc_sounds`) | BBC live stream URIs (`…/vpid/bbc_radio_two/…`, `…/bbc_radio_two.m3u8`) | Current track (artist, title, art) while music is playing; otherwise the programme title, station and programme image. Polled every 20 s. |

The BBC data comes from `rms.api.bbc.co.uk`, the API the BBC Sounds web app
uses. It is unofficial and could change.

## Installation

**HACS:** add this repository as a custom repository (category *Integration*),
install **Media Metadata Patcher**, and restart Home Assistant.

**Manual:** copy `custom_components/media_metadata_patcher` into your Home
Assistant `config/custom_components/` folder and restart.

Then go to **Settings → Devices & services → Add integration → Media Metadata
Patcher**, pick the media player to wrap, and choose which sources may fill
it. Change the sources later from the integration's **Configure** button.

## Adding a source

1. Create `custom_components/media_metadata_patcher/sources/<name>.py` with a
   subclass of `MetadataSource` (see `sources/base.py`):
   - `key`, `name`, `poll_interval`
   - `match(media_content_id) -> lookup key | None`: cheap, no I/O
   - `async_fetch(session, lookup_key) -> Metadata | None`
2. Add it to `SOURCES` in `sources/__init__.py`. Order is match priority.
3. Add tests under `tests/sources/`.

`Metadata` fields left as `None` are taken from the wrapped player, so a
source only needs to supply what's missing. Set `is_live=True` for live
streams to drop duration and position.

## Development

```sh
uv sync              # installs Python 3.14 deps incl. pytest-homeassistant-custom-component
uv run pytest
```

The brand icon (`custom_components/media_metadata_patcher/brand/`) is generated
by `scripts/brand_icon.py`:

```sh
uv run --no-project --with pillow python scripts/brand_icon.py
```

## License

MIT
