from homeassistant import config_entries
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.media_metadata_patcher.const import CONF_SOURCES, DOMAIN


async def test_user_flow_creates_entry(hass):
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ENTITY_ID: "media_player.kitchen", CONF_SOURCES: ["bbc_sounds"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen (patched)"
    assert result["options"] == {
        CONF_ENTITY_ID: "media_player.kitchen",
        CONF_SOURCES: ["bbc_sounds"],
    }


async def test_custom_name_and_duplicate_abort(hass):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="media_player.kitchen",
        options={CONF_ENTITY_ID: "media_player.kitchen"},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ENTITY_ID: "media_player.kitchen", CONF_NAME: "Kitchen BBC"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_changes_sources(hass):
    hass.states.async_set("media_player.kitchen", "idle")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="media_player.kitchen",
        title="Kitchen (patched)",
        options={CONF_ENTITY_ID: "media_player.kitchen", CONF_SOURCES: ["bbc_sounds"]},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SOURCES: []}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ENTITY_ID: "media_player.kitchen", CONF_SOURCES: []}
