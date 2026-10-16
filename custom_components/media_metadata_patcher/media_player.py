"""A media player that mirrors another one and fills in missing metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.media_player import (
    ATTR_GROUP_MEMBERS,
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_ANNOUNCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_ENQUEUE,
    ATTR_MEDIA_EXTRA,
    ATTR_MEDIA_REPEAT,
    ATTR_MEDIA_SEEK_POSITION,
    ATTR_MEDIA_SHUFFLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    ATTR_SOUND_MODE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_CLEAR_PLAYLIST,
    SERVICE_JOIN,
    SERVICE_PLAY_MEDIA,
    SERVICE_SELECT_SOUND_MODE,
    SERVICE_SELECT_SOURCE,
    SERVICE_UNJOIN,
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ENTITY_ID,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PLAY_PAUSE,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_SEEK,
    SERVICE_MEDIA_STOP,
    SERVICE_REPEAT_SET,
    SERVICE_SHUFFLE_SET,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import ATTR_PATCHED_BY, ATTR_WRAPPED_ENTITY_ID, CONF_SOURCES
from .coordinator import SourceCoordinator, async_get_coordinator
from .patch import PatchedMedia, is_active, patch_media
from .sources import SOURCES, Metadata, MetadataSource


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MetadataPatcherPlayer(hass, entry)])


class MetadataPatcherPlayer(MediaPlayerEntity):
    """Mirrors a wrapped media player; overlays source metadata when one matches."""

    _attr_should_poll = False
    # Patched images are public URLs; pass-through images are the wrapped
    # player's entity_picture, which HA has already proxied.
    _attr_media_image_remotely_accessible = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._wrapped = entry.options[CONF_ENTITY_ID]
        enabled = entry.options.get(CONF_SOURCES, list(SOURCES))
        self._sources: list[MetadataSource] = [
            source_cls() for key, source_cls in SOURCES.items() if key in enabled
        ]
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self.device_entry = async_entity_id_to_device(hass, self._wrapped)

        self._match: tuple[MetadataSource, str] | None = None
        self._coordinator: SourceCoordinator | None = None
        self._unsub_coordinator: Callable[[], None] | None = None
        self._patched = patch_media(None, {}, None)

    # --- state tracking -----------------------------------------------------

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_wrapped_change(event: Event[EventStateChangedData]) -> None:
            self.async_set_context(event.context)
            self._async_update_from_wrapped()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._wrapped], _on_wrapped_change)
        )
        self.async_on_remove(self._async_unsubscribe)
        self._async_update_from_wrapped()

    @callback
    def _async_unsubscribe(self) -> None:
        if self._unsub_coordinator is not None:
            self._unsub_coordinator()
        self._unsub_coordinator = None
        self._coordinator = None
        self._match = None

    @callback
    def _async_find_match(self, state: str | None, content_id: str | None) -> tuple[MetadataSource, str] | None:
        if not is_active(state):
            return None
        for source in self._sources:
            if (lookup_key := source.match(content_id)) is not None:
                return source, lookup_key
        return None

    @callback
    def _async_update_from_wrapped(self) -> None:
        wrapped = self.hass.states.get(self._wrapped)
        if wrapped is None or wrapped.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._attr_available = False
            self._async_unsubscribe()
            return
        self._attr_available = True
        attrs = wrapped.attributes

        match = self._async_find_match(wrapped.state, attrs.get(ATTR_MEDIA_CONTENT_ID))
        if match != self._match:
            self._async_unsubscribe()
            if match is not None:
                coordinator = async_get_coordinator(self.hass, *match)
                self._unsub_coordinator = coordinator.async_add_listener(
                    self._on_coordinator_update
                )
                self._coordinator = coordinator
                self._match = match
                self.hass.async_create_task(coordinator.async_request_refresh())

        self._attr_state = MediaPlayerState(wrapped.state) if wrapped.state in MediaPlayerState else None
        self._attr_supported_features = MediaPlayerEntityFeature(
            attrs.get("supported_features", 0)
        )
        self._attr_volume_level = attrs.get("volume_level")
        self._attr_is_volume_muted = attrs.get("is_volume_muted")
        self._attr_media_content_id = attrs.get("media_content_id")
        self._attr_media_content_type = attrs.get("media_content_type")
        self._attr_media_channel = attrs.get("media_channel")
        self._attr_media_playlist = attrs.get("media_playlist")
        self._attr_app_name = attrs.get("app_name")
        self._attr_source = attrs.get("source")
        self._attr_source_list = attrs.get("source_list")
        self._attr_sound_mode = attrs.get("sound_mode")
        self._attr_sound_mode_list = attrs.get("sound_mode_list")
        self._attr_shuffle = attrs.get("shuffle")
        self._attr_repeat = attrs.get("repeat")
        self._attr_group_members = attrs.get("group_members")
        self._patched = patch_media(wrapped.state, attrs, self._metadata)

    @property
    def _metadata(self) -> Metadata | None:
        if self._coordinator is None or not self._coordinator.last_update_success:
            return None
        return self._coordinator.data

    @callback
    def _on_coordinator_update(self) -> None:
        self._async_update_from_wrapped()
        self.async_write_ha_state()

    # --- presented metadata -------------------------------------------------

    @property
    def media_title(self) -> str | None:
        return self._patched.title

    @property
    def media_artist(self) -> str | None:
        return self._patched.artist

    @property
    def media_album_name(self) -> str | None:
        return self._patched.album

    @property
    def media_duration(self) -> int | None:
        return self._patched.duration

    @property
    def media_position(self) -> int | None:
        return self._patched.position

    @property
    def media_position_updated_at(self):
        return self._patched.position_updated_at

    @property
    def media_image_url(self) -> str | None:
        return self._patched.image_url if self._patched.patched else None

    @property
    def entity_picture(self) -> str | None:
        if self.state == MediaPlayerState.OFF:
            return None
        return self._patched.image_url

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_WRAPPED_ENTITY_ID: self._wrapped,
            ATTR_PATCHED_BY: self._match[0].key if self._match and self._patched.patched else None,
        }

    # --- commands: forwarded to the wrapped player -----------------------

    async def _async_forward(self, service: str, data: dict[str, Any] | None = None) -> None:
        await self.hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            service,
            {**(data or {}), ATTR_ENTITY_ID: self._wrapped},
            blocking=True,
            context=self._context,
        )

    async def async_turn_on(self) -> None:
        await self._async_forward(SERVICE_TURN_ON)

    async def async_turn_off(self) -> None:
        await self._async_forward(SERVICE_TURN_OFF)

    async def async_volume_up(self) -> None:
        await self._async_forward(SERVICE_VOLUME_UP)

    async def async_volume_down(self) -> None:
        await self._async_forward(SERVICE_VOLUME_DOWN)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._async_forward(SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: volume})

    async def async_mute_volume(self, mute: bool) -> None:
        await self._async_forward(SERVICE_VOLUME_MUTE, {ATTR_MEDIA_VOLUME_MUTED: mute})

    async def async_media_play(self) -> None:
        await self._async_forward(SERVICE_MEDIA_PLAY)

    async def async_media_pause(self) -> None:
        await self._async_forward(SERVICE_MEDIA_PAUSE)

    async def async_media_play_pause(self) -> None:
        await self._async_forward(SERVICE_MEDIA_PLAY_PAUSE)

    async def async_media_stop(self) -> None:
        await self._async_forward(SERVICE_MEDIA_STOP)

    async def async_media_previous_track(self) -> None:
        await self._async_forward(SERVICE_MEDIA_PREVIOUS_TRACK)

    async def async_media_next_track(self) -> None:
        await self._async_forward(SERVICE_MEDIA_NEXT_TRACK)

    async def async_media_seek(self, position: float) -> None:
        await self._async_forward(SERVICE_MEDIA_SEEK, {ATTR_MEDIA_SEEK_POSITION: position})

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        data = {ATTR_MEDIA_CONTENT_TYPE: media_type, ATTR_MEDIA_CONTENT_ID: media_id}
        for key in (ATTR_MEDIA_ENQUEUE, ATTR_MEDIA_ANNOUNCE, ATTR_MEDIA_EXTRA):
            if kwargs.get(key) is not None:
                data[key] = kwargs[key]
        await self._async_forward(SERVICE_PLAY_MEDIA, data)

    async def async_select_source(self, source: str) -> None:
        await self._async_forward(SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: source})

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        await self._async_forward(SERVICE_SELECT_SOUND_MODE, {ATTR_SOUND_MODE: sound_mode})

    async def async_clear_playlist(self) -> None:
        await self._async_forward(SERVICE_CLEAR_PLAYLIST)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._async_forward(SERVICE_SHUFFLE_SET, {ATTR_MEDIA_SHUFFLE: shuffle})

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._async_forward(SERVICE_REPEAT_SET, {ATTR_MEDIA_REPEAT: repeat})

    async def async_join_players(self, group_members: list[str]) -> None:
        await self._async_forward(SERVICE_JOIN, {ATTR_GROUP_MEMBERS: group_members})

    async def async_unjoin_player(self) -> None:
        await self._async_forward(SERVICE_UNJOIN)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        component: EntityComponent[MediaPlayerEntity] = self.hass.data[MEDIA_PLAYER_DOMAIN]
        if entity := component.get_entity(self._wrapped):
            return await entity.async_browse_media(media_content_type, media_content_id)
        raise NotImplementedError
