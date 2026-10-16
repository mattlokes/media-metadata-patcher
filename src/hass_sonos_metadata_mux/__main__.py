"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp

from . import bbc, sonos
from .config import Config, ConfigError, PlayerConfig, load_config
from .mux import mux

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


async def _speaker(cfg: Config, args: argparse.Namespace):
    if getattr(args, "host", None) or getattr(args, "name", None):
        host, name = args.host, args.name
    else:
        player = _player(cfg, args.player)
        host, name = player.sonos_host, player.sonos_name
    return await asyncio.to_thread(sonos.resolve_speaker, host, name)


# --- sonos-dump -------------------------------------------------------------


async def cmd_sonos_dump(cfg: Config, args: argparse.Namespace) -> None:
    speaker = await _speaker(cfg, args)
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
            record = {"t": time.time(), "service": service, "variables": variables}
            log.write(json.dumps(record, default=_json_default) + "\n")
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


# --- bbc --------------------------------------------------------------------


async def cmd_bbc(cfg: Config, args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession() as session:
        now = await bbc.BbcClient(session, cfg.bbc.image_size).now_playing(args.service)
    print(_dumps(asdict(now)))


# --- preview ----------------------------------------------------------------


async def cmd_preview(cfg: Config, args: argparse.Namespace) -> None:
    """Print what the HA entity would show, without touching MQTT."""
    player = sonos.SonosPlayer(await _speaker(cfg, args))
    last: dict[str, Any] | None = None

    async with aiohttp.ClientSession() as session:
        client = bbc.BbcClient(session, cfg.bbc.image_size)

        async def show() -> None:
            nonlocal last
            snap = await player.snapshot()
            service = bbc.service_id_from_uris(snap.uris)
            now = await client.now_playing(service) if service else None
            muxed = asdict(mux(snap, now))
            if muxed != last:
                stamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{stamp}] " + json.dumps(muxed, indent=2), flush=True)
                last = muxed

        await show()
        if not args.watch:
            return

        sonos.configure_soco(cfg.sonos)
        changed = asyncio.Event()
        await player.subscribe(lambda _service, _vars: changed.set(), lambda ex: None)
        deadline = time.monotonic() + args.watch
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    await asyncio.wait_for(changed.wait(), min(remaining, cfg.bbc.poll_interval))
                except TimeoutError:
                    pass
                changed.clear()
                await show()
        finally:
            await player.unsubscribe()
            await sonos.stop_event_listener()


# --- main -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hass-sonos-metadata-mux")
    parser.add_argument("-c", "--config", type=Path, default=Path("config.toml"))
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    def speaker_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--player", help="player id from the config")
        p.add_argument("--host", help="speaker IP or hostname instead of --player")
        p.add_argument("--name", help="speaker room name instead of --player")

    p = sub.add_parser("sonos-dump", help="dump raw Sonos state for a speaker")
    speaker_args(p)
    p.add_argument("--watch", type=float, metavar="SECONDS", help="also record events")
    p.add_argument("--out", default="fixtures/raw", help="output directory")
    p.set_defaults(func=cmd_sonos_dump)

    p = sub.add_parser("bbc", help="show BBC now-playing for a service id")
    p.add_argument("service", help="e.g. bbc_radio_two, bbc_6music")
    p.set_defaults(func=cmd_bbc)

    p = sub.add_parser("preview", help="show the merged metadata for a speaker")
    speaker_args(p)
    p.add_argument("--watch", type=float, metavar="SECONDS", help="keep updating")
    p.set_defaults(func=cmd_preview)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
