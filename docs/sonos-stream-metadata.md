# What a Sonos reports for different streams

Notes from a test on **2026-10-16**. A Sonos speaker with Alexa built-in
was asked by voice to play several services. SoCo recorded what the speaker
reported:

- **UPnP events:** AVTransport `NOTIFY`s (`sonos-dump --watch`)
- **Snapshots:** `get_current_track_info()` / `get_current_media_info()`

Alexa's own now-playing API was queried the whole time. Tokens, serials and
listener IDs in URIs below are redacted (`…`).

## Summary

| Requested via Alexa | How the Sonos plays it | Title | Artist | Album | Art | Duration |
|---|---|---|---|---|---|---|
| **BBC Sounds** (Radio 2) | Direct BBC HLS stream | ❌ `bbc_radio_two.m3u8` / blank | ❌ | ❌ | ❌ (only a generic `/getaa` placeholder) | live (`0:00:00`) |
| **Smooth** (Global Player skill) | Sonos queue → live MP3 stream | ✅ station name | — | — | ✅ station logo | live |
| **Apple Music** | Sonos queue, HLS track | ✅ | ✅ | ✅ | ✅ | ✅ `0:03:28` |
| **Amazon Music** | Sonos queue, HLS track | ✅ | ✅ | ✅ | ✅ | ✅ `0:03:41` |
| **Smooth** (via TuneIn) | TuneIn radio stream | ✅ station name | ✅ via stream text | — | ✅ station logo | live |

Findings:

- **Only BBC Sounds lacks metadata.** Every other service fills in the
  Sonos's DIDL metadata (`current_track_meta_data`) the way Home Assistant's
  Sonos integration expects. (Not yet checked on the HA side.)
- **Alexa is just the launcher.** It hands the Sonos an ordinary stream URL or
  queue item, and the Sonos plays it itself. Amazon's API had **no now-playing
  data** for any Sonos device (`/api/np/player` all `null`). The HTTP2 push
  stream sent **zero events** in 4 minutes covering six requests and track changes.
- **No `x-sonos-vli:` URIs appeared.** In SoCo's source table, `x-sonos-vli:`
  ("voice line-in") URIs are used for AirPlay (`…,airplay:`) and Spotify
  Connect (`…,spotify:`). Alexa-initiated playback here never used them.
- **Live radio offers fewer transport actions.** `current_transport_actions`
  is `Set, Stop, Play` for radio streams, with no Pause or Next. On-demand
  tracks add `Pause, Next, X_DLNA_SeekTrackNr`. Pause on a BBC stream may need
  to become Stop.

## Per-service detail

### BBC Sounds (`bbc_radio_two`)

```
av_transport_uri:  x-rincon-mp3radio://https://open.live.bbc.co.uk/mediaselector/6/redir/version/2.0/vpid/bbc_radio_two/mediaset/voice-hls/proto/https?jwt_auth=…
current_track_uri: hls-radio://https://a.files.bbci.co.uk/ms6/live/<uuid>/audio/simulcast/hls/uk/voice_sbr_v1/aks/bbc_radio_two.m3u8
metadata:          dc:title = "bbc_radio_two.m3u8"   (media channel = " ")
music_source:      RADIO
```

- **What's reported:** the only "title" is the HLS playlist filename. SoCo
  treats it as a URI fragment and returns an empty title.
- **What can be used:** the BBC **service ID** appears in both URIs, as
  `vpid/<id>` in the media URI and `<id>.m3u8` in the track URI.
- **Where the metadata is:** the BBC Sounds web app's API resolves the ID
  without authentication:
  - `GET https://rms.api.bbc.co.uk/v2/broadcasts/poll/<id>` gives the
    programme schedule, network name, programme image and station logo
    template.
  - `GET https://rms.api.bbc.co.uk/v2/services/<id>/segments/latest?experience=domestic&offset=0&limit=1`
    gives the current music segment (artist, title, image), flagged
    `offset.now_playing: true`. It returns an empty `data` list on talk
    stations such as `bbc_radio_fourfm`.
  - Image URLs carry a `{recipe}` placeholder that must be filled with a
    size, e.g. `640x640`. Logos use `{type}_{size}.{format}`, e.g.
    `blocks-colour_600x600.png`.
- **The stream token:** the `jwt_auth` in the media URI is a stream token
  (`exp` about 24 h). Don't log or commit it.

### Smooth via the Global Player skill

```
1. https://audio.remixd.com/alexa/smooth_plus_2.mp3   (13 s intro, queued; title + logo)
2. https://media-ssl.musicradio.com/SmoothHerts?dax_player=GlobalPlayer&dax_platform=Alexa&dax_listenerid=…
   av_transport_uri: x-rincon-queue:RINCON_…#4
   metadata: title "Smooth Herts, Beds and Bucks", albumArtURI images.musicrad.io/…
```

- For about two seconds the live stream reported empty metadata, then the
  station title and logo came back.
- There's no song info, only the station.

### Apple Music

```
av_transport_uri:  x-rincon-queue:RINCON_…#4
current_track_uri: https://play.itunes.apple.com/WebObjects/MZPlay.woa/hls/aod-master-playlist.m3u8?token=…&adam-id=992221997&store-front=143444
metadata: title "Supermassive Black Hole", creator "Muse", album "Supermassive Black Hole",
          albumArtURI https://is1-ssl.mzstatic.com/image/thumb/…
duration: 0:03:28
```

### Amazon Music

```
av_transport_uri:  x-rincon-queue:RINCON_…#4
current_track_uri: https://d2qhcol036tlr5.cloudfront.net/api/manifest.m3u8?dmid=202987900&…
metadata: title "Hungry Like The Wolf (2001 Remastered Version)", creator "Duran Duran", album "Rio",
          albumArtURI https://m.media-amazon.com/images/I/712XJif-X-L._UL600_.jpg
duration: 0:03:41
```

"Alexa, next" produced a normal track change with fresh metadata.

### Smooth via TuneIn

```
av_transport_uri: x-rincon-mp3radio://https://opml.radiotime.com/Tune.ashx?…&id=s46556&partnerId=…
track sequence:
  1. …/Jimmy_TI_SonicLogo_D_Welcome.mp3     streamContent ZPSTR_CONNECTING → ZPSTR_BUFFERING
  2. …/nobump_sonic_pre.mp3?aw_0_1st…         (pre-roll ad)
  3. x-rincon-mp3radio://https://media-ssl.musicradio.com/SmoothHertsMP3
     title "SmoothHertsMP3", art cdn-profiles.tunein.com/s221129/images/logoq.jpg
     r:streamContent "George Benson - Give Me The Night"
```

- **Song info:** the live stream carries ICY "now playing" text in
  `r:streamContent`. SoCo's `get_current_track_info()` splits it on `" - "`
  into artist and title.
- **Transient junk:** the welcome jingle and ad pre-roll show up briefly as
  "tracks" with URL-ish titles. SoCo suppresses titles that repeat the URI.
- **Status codes:** `ZPSTR_CONNECTING` / `ZPSTR_BUFFERING` are status codes,
  not track text.

## What this means for the mux

- **Detecting BBC:** look for a BBC service ID in the track or media URI
  (`bbc.co.uk/mediaselector/…/vpid/<id>` or `bbci.co.uk/…/<id>.m3u8`).
- **BBC metadata:**
  - **Music playing:** title, artist and art come from the segment, and the
    programme title goes in the album slot.
  - **Talk:** the programme title, then station, then episode subtitle, with
    the programme image.
  - **Missing art:** fall back to the programme image, then the station logo.
- **Everything else:** pass Sonos metadata through unchanged.
- **Stopped speakers:** a `STOPPED` speaker keeps its last URI, so don't show
  BBC metadata unless it is playing or paused.
- **Track changes within a stream:** no UPnP event fires when the BBC track
  changes, so BBC streams need polling (every 20 s by default).
