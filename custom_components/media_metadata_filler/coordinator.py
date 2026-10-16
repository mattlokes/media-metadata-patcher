"""Shared polling of metadata sources.

One coordinator per (source, lookup key), so two players on the same BBC
station share one poll. A DataUpdateCoordinator only polls while it has
listeners, so an idle coordinator costs nothing.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .sources import Metadata, MetadataSource

_LOGGER = logging.getLogger(__name__)

type SourceCoordinator = DataUpdateCoordinator[Metadata | None]

_COORDINATORS: HassKey[dict[tuple[str, str], SourceCoordinator]] = HassKey(
    f"{DOMAIN}_coordinators"
)


def async_get_coordinator(
    hass: HomeAssistant, source: MetadataSource, lookup_key: str
) -> SourceCoordinator:
    """Return the shared coordinator for a source and lookup key."""
    coordinators = hass.data.setdefault(_COORDINATORS, {})
    key = (source.key, lookup_key)
    if (coordinator := coordinators.get(key)) is None:
        session = async_get_clientsession(hass)

        async def _update() -> Metadata | None:
            return await source.async_fetch(session, lookup_key)

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            # Shared across config entries, so not tied to any one entry.
            config_entry=None,
            name=f"{DOMAIN} {source.key} {lookup_key}",
            update_interval=source.poll_interval,
            update_method=_update,
            always_update=False,
        )
        coordinators[key] = coordinator
    return coordinator
