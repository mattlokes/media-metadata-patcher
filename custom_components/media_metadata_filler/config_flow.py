"""Config flow: choose a media player to wrap and which sources may fill it."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import CONF_SOURCES, DOMAIN
from .sources import SOURCES


def _sources_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=key, label=cls.name) for key, cls in SOURCES.items()],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


class MetadataFillerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            entity_id = user_input[CONF_ENTITY_ID]
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()
            name = user_input.get(CONF_NAME) or self._default_name(entity_id)
            return self.async_create_entry(
                title=name,
                data={},
                options={
                    CONF_ENTITY_ID: entity_id,
                    CONF_SOURCES: user_input.get(CONF_SOURCES, list(SOURCES)),
                },
            )

        own_entities = [
            entry.entity_id
            for entry in er.async_get(self.hass).entities.values()
            if entry.platform == DOMAIN
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(domain=MEDIA_PLAYER_DOMAIN, exclude_entities=own_entities)
                ),
                vol.Optional(CONF_NAME): TextSelector(),
                vol.Required(CONF_SOURCES, default=list(SOURCES)): _sources_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    def _default_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        base = state.name if state else entity_id
        return f"{base} (filled)"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MetadataFillerOptionsFlow()


class MetadataFillerOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_SOURCES: user_input[CONF_SOURCES]}
            )
        current = self.config_entry.options.get(CONF_SOURCES, list(SOURCES))
        schema = vol.Schema({vol.Required(CONF_SOURCES, default=current): _sources_selector()})
        return self.async_show_form(step_id="init", data_schema=schema)
