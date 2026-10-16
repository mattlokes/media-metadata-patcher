"""Alexa access via alexapy: enrollment, login, device lookup and now-playing.

Authentication uses alexapy's paste-URL enrollment (`alexapy.secureauth`), so
no Amazon password or TOTP seed is ever stored; only the device refresh token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from alexapy import (
    AlexaAPI,
    AlexaLogin,
    AuthTerminalError,
    AuthTransientError,
    DeviceCredentials,
    EnrollmentFlow,
    HTTP2EchoClient,
    TokenManager,
)

from .config import APP_NAME

_LOGGER = logging.getLogger(__name__)

# Push commands that mean a device's now-playing state may have changed.
MEDIA_PUSH_COMMANDS = frozenset(
    {
        "PUSH_AUDIO_PLAYER_STATE",
        "PUSH_MEDIA_CHANGE",
        "PUSH_MEDIA_PROGRESS_CHANGE",
        "PUSH_MEDIA_QUEUE_CHANGE",
        "PUSH_VOLUME_CHANGE",
    }
)

AlexaAuthError = AuthTerminalError
AlexaTransientError = AuthTransientError


def _write_private_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def load_credentials(path: Path) -> DeviceCredentials | None:
    try:
        return DeviceCredentials.from_dict(json.loads(path.read_text()))
    except FileNotFoundError:
        return None


def save_credentials(path: Path, creds: DeviceCredentials) -> None:
    _write_private_json(path, creds.as_dict())


def start_enrollment(domain: str, state_file: Path) -> str:
    """Begin enrollment; persist the PKCE state and return the login URL."""
    flow = EnrollmentFlow(domain=domain)
    _write_private_json(state_file, flow.to_state())
    return flow.oauth_url


async def finish_enrollment(
    state_file: Path, pasted_url: str, credentials_file: Path
) -> DeviceCredentials:
    """Exchange the pasted maplanding URL for device credentials and save them."""
    try:
        state = json.loads(state_file.read_text())
    except FileNotFoundError as ex:
        raise RuntimeError(
            "No enrollment in progress; run `enroll` without --url first"
        ) from ex
    flow = EnrollmentFlow.from_state(state)
    code = flow.parse_redirect_url(pasted_url)
    async with aiohttp.ClientSession() as session:
        creds = await flow.async_register(session, code)
    save_credentials(credentials_file, creds)
    state_file.unlink(missing_ok=True)
    return creds


@dataclass(frozen=True)
class AlexaDevice:
    """The attributes `AlexaAPI` reads from its device object."""

    name: str
    device_serial_number: str
    _device_type: str
    _locale: str = "en-US"
    family: str = ""
    online: bool | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> AlexaDevice:
        return cls(
            name=raw.get("accountName", ""),
            device_serial_number=raw["serialNumber"],
            _device_type=raw["deviceType"],
            _locale=raw.get("locale") or "en-US",
            family=raw.get("deviceFamily", ""),
            online=raw.get("online"),
        )


def parse_push_message(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Unpack an HTTP2 push directive into (command, payload) pairs.

    Mirrors alexa_media's http2_handler: each renderingUpdate carries a JSON
    string `resourceMetadata` whose `payload` is itself a JSON string.
    """
    updates = message.get("directive", {}).get("payload", {}).get("renderingUpdates", [])
    out: list[tuple[str, dict[str, Any]]] = []
    for item in updates:
        try:
            resource = json.loads(item.get("resourceMetadata", ""))
            command = resource.get("command")
            payload = json.loads(resource.get("payload") or "null")
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
        if command and isinstance(payload, dict):
            out.append((command, payload))
    return out


def push_serial(payload: dict[str, Any]) -> str | None:
    """Return the device serial a push payload refers to, if any."""
    doppler = payload.get("dopplerId")
    if isinstance(doppler, dict) and doppler.get("deviceSerialNumber"):
        return doppler["deviceSerialNumber"]
    key = payload.get("key")
    if isinstance(key, dict):
        entry_id = key.get("entryId", "")
        if entry_id.count("#") >= 2:
            return entry_id.split("#")[2]
        if key.get("serialNumber"):
            return key["serialNumber"]
    return None


class AlexaClient:
    """An authenticated alexapy session for one Amazon account."""

    def __init__(self, domain: str, credentials: DeviceCredentials, state_dir: Path):
        self._domain = domain
        self._creds = credentials
        self._state_dir = state_dir
        self._login: AlexaLogin | None = None
        self._apis: dict[str, AlexaAPI] = {}
        self._push: HTTP2EchoClient | None = None

    @property
    def login_obj(self) -> AlexaLogin:
        if self._login is None:
            raise RuntimeError("AlexaClient.connect() has not been called")
        return self._login

    async def connect(self) -> None:
        """Log in from the stored refresh token.

        Raises AlexaAuthError if Amazon rejects the token (re-enroll needed)
        and AlexaTransientError for network or throttling problems.
        """
        # alexapy writes its cookie jar under <outputpath>/.storage/.
        (self._state_dir / ".storage").mkdir(parents=True, exist_ok=True)
        login = AlexaLogin(
            url=self._domain,
            # No "@" tells alexapy not to match the account email after login.
            email=APP_NAME,
            password="",
            outputpath=lambda p: str(self._state_dir / p),
            oauth={
                "refresh_token": self._creds.refresh_token,
                "mac_dms": self._creds.mac_dms,
            },
            uuid=self._creds.serial,
        )
        # Classify refresh-token failures before handing over to alexapy, which
        # would otherwise fall back to scraping the password login page.
        tokens = TokenManager(self._creds)
        async with aiohttp.ClientSession() as session:
            login.access_token = await tokens.async_refresh_access_token(session)
        if not (
            await login.exchange_token_for_cookies()
            and await login.get_csrf()
            and await login.test_loggedin(rebuild_session=False)
        ):
            await login.close()
            raise AlexaTransientError("Alexa session could not be established")
        self._login = login
        self._apis.clear()
        _LOGGER.info("Logged in to Alexa (%s)", self._domain)

    async def close(self) -> None:
        if self._push is not None:
            for task in list(getattr(self._push, "_tasks", ())):
                task.cancel()
            await self._push.client.aclose()
            self._push = None
        if self._login is not None:
            await self._login.close()
            self._login = None

    async def devices(self) -> list[AlexaDevice]:
        raw = await AlexaAPI.get_devices(self.login_obj) or []
        return [AlexaDevice.from_api(d) for d in raw if d.get("serialNumber")]

    async def find_device(self, name_or_serial: str) -> AlexaDevice:
        devices = await self.devices()
        for dev in devices:
            if name_or_serial in (dev.device_serial_number, dev.name):
                return dev
        lowered = name_or_serial.casefold()
        for dev in devices:
            if dev.name.casefold() == lowered:
                return dev
        names = ", ".join(sorted(d.name for d in devices))
        raise LookupError(f"No Alexa device named {name_or_serial!r}. Known: {names}")

    def _api(self, device: AlexaDevice) -> AlexaAPI:
        api = self._apis.get(device.device_serial_number)
        if api is None:
            api = AlexaAPI(device, self.login_obj)
            self._apis[device.device_serial_number] = api
        return api

    async def now_playing(self, device: AlexaDevice) -> dict[str, Any] | None:
        """Raw `/api/np/player` response for a device."""
        return await self._api(device).get_state()

    async def next_track(self, device: AlexaDevice) -> None:
        await self._api(device).next()

    async def previous_track(self, device: AlexaDevice) -> None:
        await self._api(device).previous()

    async def start_push(
        self,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        on_close: Callable[[], Awaitable[None]],
    ) -> None:
        """Open Amazon's HTTP2 push stream; `on_message` gets each raw directive."""

        async def _opened() -> None:
            _LOGGER.info("Alexa push stream open")

        async def _error(message: str) -> None:
            _LOGGER.warning("Alexa push stream error: %s", message)

        self._push = HTTP2EchoClient(
            self.login_obj,
            msg_callback=on_message,
            open_callback=_opened,
            close_callback=on_close,
            error_callback=_error,
            loop=asyncio.get_running_loop(),
        )
        await self._push.async_run()
