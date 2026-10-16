"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import alexa, sonos
from .config import Config, ConfigError, PlayerConfig, load_config

_LOGGER = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:  # noqa: BLE001 - fall back to str for odd DIDL objects
            pass
    return str(value)


def _dumps(data: Any) -> str:
    return json.dumps(data, indent=2, default=_json_default)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _player(cfg: Config, player_id: str | None) -> PlayerConfig:
    if player_id is None:
        if len(cfg.players) == 1:
            return cfg.players[0]
        raise SystemExit("Several players configured; pass --player <id>")
    for player in cfg.players:
        if player.id == player_id:
            return player
    raise SystemExit(f"No player with id {player_id!r} in config")


async def _alexa_client(cfg: Config) -> alexa.AlexaClient:
    creds = alexa.load_credentials(cfg.alexa_credentials_file)
    if creds is None:
        raise SystemExit("Not enrolled with Amazon yet; run the `enroll` command first")
    client = alexa.AlexaClient(cfg.alexa.domain, creds, cfg.state_dir)
    try:
        await client.connect()
    except alexa.AlexaAuthError as ex:
        raise SystemExit(f"Amazon rejected the stored credentials ({ex}); run `enroll` again") from ex
    return client


# --- enroll -----------------------------------------------------------------


async def cmd_enroll(cfg: Config, args: argparse.Namespace) -> None:
    if args.url is None:
        url = alexa.start_enrollment(cfg.alexa.domain, cfg.enroll_state_file)
        print(
            "1. Open this URL in a browser and sign in to Amazon:\n\n"
            f"   {url}\n\n"
            "2. After signing in you'll land on a page that may look blank or say\n"
            '   "Looking for Something?". That is expected. Copy the full address from\n'
            "   the address bar; it starts with https://www.amazon.com/ap/maplanding\n"
        )
        if not sys.stdin.isatty():
            print("Then run: enroll --url '<pasted address>'")
            return
        args.url = input("3. Paste the address here: ").strip()
    creds = await alexa.finish_enrollment(
        cfg.enroll_state_file, args.url, cfg.alexa_credentials_file
    )
    print(f"Enrolled. Credentials saved to {cfg.alexa_credentials_file}")
    _LOGGER.debug("Enrolled device serial %s", creds.serial)


# --- alexa ------------------------------------------------------------------


async def cmd_alexa_devices(cfg: Config, args: argparse.Namespace) -> None:
    client = await _alexa_client(cfg)
    try:
        devices = await client.devices()
    finally:
        await client.close()
    rows = sorted(devices, key=lambda d: d.name.casefold())
    width = max((len(d.name) for d in rows), default=4)
    print(f"{'NAME':<{width}}  {'SERIAL':<18}  {'TYPE':<16}  FAMILY  ONLINE")
    for d in rows:
        print(
            f"{d.name:<{width}}  {d.device_serial_number:<18}  "
            f"{d._device_type:<16}  {d.family}  {d.online}"
        )


async def cmd_alexa_dump(cfg: Config, args: argparse.Namespace) -> None:
    device_ref = args.device or _player(cfg, args.player).alexa_device
    if not device_ref:
        raise SystemExit("Pass --device, or set alexa_device for the player")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = await _alexa_client(cfg)
    try:
        device = await client.find_device(device_ref)
        state = await client.now_playing(device)
        print(_dumps(state))
        path = out_dir / f"alexa_np_{_stamp()}.json"
        path.write_text(_dumps(state))
        print(f"\nSaved {path}", file=sys.stderr)

        if args.watch:
            await _alexa_watch(client, device, out_dir, args.watch)
    finally:
        await client.close()


async def _alexa_watch(
    client: alexa.AlexaClient, device: alexa.AlexaDevice, out_dir: Path, seconds: float
) -> None:
    log_path = out_dir / f"alexa_push_{_stamp()}.jsonl"
    closed = asyncio.Event()

    with log_path.open("w") as log:

        def record(kind: str, data: Any) -> None:
            log.write(json.dumps({"t": time.time(), "kind": kind, "data": data}, default=str) + "\n")
            log.flush()

        async def on_message(message: dict[str, Any]) -> None:
            record("push", message)
            for command, payload in alexa.parse_push_message(message):
                serial = alexa.push_serial(payload)
                print(f"push {command} serial={serial}", file=sys.stderr)
                if command in alexa.MEDIA_PUSH_COMMANDS and serial == device.device_serial_number:
                    state = await client.now_playing(device)
                    record("np_player", state)
                    info = (state or {}).get("playerInfo", {}).get("infoText") or {}
                    print(f"  now playing: {info}", file=sys.stderr)

        async def on_close() -> None:
            closed.set()

        await client.start_push(on_message, on_close)
        print(f"Watching Alexa push for {seconds:.0f}s → {log_path}", file=sys.stderr)
        try:
            await asyncio.wait_for(closed.wait(), timeout=seconds)
            print("Push stream closed early", file=sys.stderr)
        except TimeoutError:
            pass


# --- sonos ------------------------------------------------------------------


async def cmd_sonos_dump(cfg: Config, args: argparse.Namespace) -> None:
    if args.host or args.name:
        host, name = args.host, args.name
    else:
        player = _player(cfg, args.player)
        host, name = player.sonos_host, player.sonos_name
    speaker = await asyncio.to_thread(sonos.resolve_speaker, host, name)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    dump = await asyncio.to_thread(sonos.raw_dump, speaker)
    print(_dumps(dump))
    slug = dump["player_name"].lower().replace(" ", "_")
    path = out_dir / f"sonos_{slug}_{_stamp()}.json"
    path.write_text(_dumps(dump))
    print(f"\nSaved {path}", file=sys.stderr)

    if not args.watch:
        return
    sonos.configure_soco(cfg.sonos)
    player = sonos.SonosPlayer(speaker)
    log_path = out_dir / f"sonos_events_{slug}_{_stamp()}.jsonl"
    with log_path.open("w") as log:

        def on_event(service: str, variables: dict[str, Any]) -> None:
            log.write(
                json.dumps({"t": time.time(), "service": service, "variables": variables}, default=_json_default)
                + "\n"
            )
            log.flush()
            print(f"event {service}: {sorted(variables)}", file=sys.stderr)

        def on_renew_fail(ex: Exception) -> None:
            print(f"subscription renewal failed: {ex}", file=sys.stderr)

        await player.subscribe(on_event, on_renew_fail)
        print(f"Watching Sonos events for {args.watch:.0f}s → {log_path}", file=sys.stderr)
        try:
            await asyncio.sleep(args.watch)
        finally:
            await player.unsubscribe()
            await sonos.stop_event_listener()


# --- main -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hass-sonos-metadata-mux")
    parser.add_argument("-c", "--config", type=Path, default=Path("config.toml"))
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("enroll", help="link this app to your Amazon account")
    p.add_argument("--url", help="the maplanding address pasted from the browser")
    p.set_defaults(func=cmd_enroll)

    p = sub.add_parser("alexa-devices", help="list Alexa devices on the account")
    p.set_defaults(func=cmd_alexa_devices)

    for name, func, help_text in (
        ("alexa-dump", cmd_alexa_dump, "dump Alexa now-playing for a device"),
        ("sonos-dump", cmd_sonos_dump, "dump raw Sonos state for a speaker"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--player", help="player id from the config")
        p.add_argument("--watch", type=float, metavar="SECONDS", help="also record events")
        p.add_argument("--out", default="fixtures/raw", help="output directory")
        p.set_defaults(func=func)
    sub.choices["alexa-dump"].add_argument("--device", help="Alexa device name or serial")
    sub.choices["sonos-dump"].add_argument("--host", help="speaker IP or hostname")
    sub.choices["sonos-dump"].add_argument("--name", help="speaker room name")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose > 1 else logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = load_config(args.config)
    except ConfigError as ex:
        raise SystemExit(str(ex)) from ex
    try:
        asyncio.run(args.func(cfg, args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
