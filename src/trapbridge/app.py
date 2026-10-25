"""Service entry point: wires receiver, mapper, correlator and dispatcher together."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from trapbridge import __version__
from trapbridge.config import AppConfig, ConfigError, load_config
from trapbridge.correlator import Correlator
from trapbridge.dispatcher import Dispatcher
from trapbridge.jira import JiraClient
from trapbridge.mapper import TrapMapper
from trapbridge.models import Trap
from trapbridge.pagerduty import PagerDutyClient

log = logging.getLogger("trapbridge")

POLL_INTERVAL_SECONDS = 5.0


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
        )


def setup_logging(level: str, as_json: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if as_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)


class StateStore:
    """Atomic JSON persistence so open incidents survive a restart."""

    def __init__(self, path: str | None) -> None:
        self._path = Path(path) if path else None

    def load(self) -> dict[str, object]:
        if self._path is None or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            log.error("could not read state file %s: %s", self._path, exc)
            return {}

    def save(self, data: dict[str, object]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".state-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self._path)


class Bridge:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.mapper = TrapMapper(cfg.rules)
        self.correlator = Correlator(cfg.correlation)
        self.jira = JiraClient(cfg.jira)
        self.pager = PagerDutyClient(cfg.pagerduty) if cfg.pagerduty else None
        self.dispatcher = Dispatcher(self.jira, self.pager)
        self.state = StateStore(cfg.state_file)
        self.queue: asyncio.Queue[Trap] = asyncio.Queue(maxsize=10_000)

    def restore(self) -> None:
        data = self.state.load()
        if data:
            self.correlator.restore(data.get("correlator", {}))  # type: ignore[arg-type]
            self.dispatcher.restore(data.get("dispatcher", {}))  # type: ignore[arg-type]
            log.info("restored %d open incident(s)", len(self.correlator.open_incidents))

    def persist(self) -> None:
        self.state.save({"correlator": self.correlator.snapshot(), "dispatcher": self.dispatcher.snapshot()})

    async def handle_trap(self, trap: Trap) -> None:
        alert = self.mapper.map(trap)
        if alert is None:
            return
        for action in self.correlator.process(alert, time.time()):
            await self.dispatcher.handle(action)
        self.persist()

    async def worker(self) -> None:
        while True:
            trap = await self.queue.get()
            try:
                await self.handle_trap(trap)
            except Exception:
                log.exception("failed to process trap %s from %s", trap.trap_oid, trap.sender)
            finally:
                self.queue.task_done()

    async def poller(self) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            actions = self.correlator.poll(time.time())
            for action in actions:
                await self.dispatcher.handle(action)
            if actions:
                self.persist()

    async def close(self) -> None:
        await self.jira.aclose()
        if self.pager:
            await self.pager.aclose()


async def run(cfg: AppConfig) -> None:
    from trapbridge.receiver import TrapReceiver  # imported lazily: pysnmp is only needed to serve

    bridge = Bridge(cfg)
    bridge.restore()
    for warning in await bridge.jira.validate():
        log.warning("startup validation: %s", warning)

    receiver = TrapReceiver(cfg.snmp, bridge.queue)
    receiver.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    tasks = [asyncio.create_task(bridge.worker()), asyncio.create_task(bridge.poller())]
    log.info("trapbridge %s started", __version__)
    await stop.wait()

    log.info("shutting down")
    receiver.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    bridge.persist()
    await bridge.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trapbridge", description=__doc__)
    parser.add_argument("-c", "--config", default="/etc/trapbridge/config.yaml", help="path to YAML config")
    parser.add_argument("--check", action="store_true", help="validate the configuration and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.log_level, cfg.log_json)
    if args.check:
        print(f"configuration OK: {len(cfg.snmp.listeners)} listener(s), {len(cfg.rules)} rule(s)")
        return 0

    asyncio.run(run(cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
