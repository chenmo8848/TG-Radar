from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events

from .compat import seed_db_from_legacy_config_if_needed
from .config import load_config
from .db import RadarDB
from .logger import setup_logger
from .plugin_manager import PluginManager
from .version import __version__


class CoreApp:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.config = load_config(work_dir)
        self.logger = setup_logger("tg-radar-core", self.config.logs_dir / "core.log")
        self.db = RadarDB(self.config.db_path)
        seed_db_from_legacy_config_if_needed(work_dir, self.db)
        self.started_at = datetime.now()
        self.stop_event = asyncio.Event()
        self.reload_event = asyncio.Event()
        self.client: TelegramClient | None = None
        self.plugin_manager = PluginManager(work_dir, self.config, logger=self.logger)
        self.revision = self.db.get_revision()

    async def _record_runtime(self, key: str, value: str) -> None:
        try:
            with self.db.tx() as conn:
                conn.execute(
                    "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value),
                )
        except Exception:
            pass

    async def perform_reload(self, trigger: str) -> None:
        self.revision = self.db.get_revision()
        await self.plugin_manager.call_core_hook("on_reload", self)
        await self._record_runtime("last_core_reload", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.db.log_event("INFO", "CORE_RELOAD", f"trigger={trigger}; revision={self.revision}")
        self.logger.info("core reloaded trigger=%s revision=%s", trigger, self.revision)

    async def run(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.core_session.with_suffix(".session").exists():
            raise FileNotFoundError("Missing runtime/sessions/tg_radar_core.session. Run bootstrap_session.py first.")

        lock_file = self.work_dir / ".core.lock"
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform != "win32":
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            raise RuntimeError("tg-radar-core is already running")

        async with TelegramClient(str(self.config.core_session), self.config.api_id, self.config.api_hash) as client:
            self.client = client
            client.parse_mode = "html"
            self.plugin_manager.load_core_plugins()
            await self.plugin_manager.call_core_hook("on_start", self)
            self.db.log_event("INFO", "CORE", f"core service started v{__version__}")
            self.logger.info("core service started version=%s revision=%s plugins=%s", __version__, self.revision, len(self.plugin_manager.core_states))

            @client.on(events.NewMessage)
            async def message_handler(event: events.NewMessage.Event) -> None:
                if not (event.is_group or event.is_channel):
                    return
                await self.plugin_manager.call_core_hook("on_message", self, event)

            async def signal_reload_watcher() -> None:
                while not self.stop_event.is_set():
                    await self.reload_event.wait()
                    self.reload_event.clear()
                    try:
                        await self.perform_reload("signal")
                    except Exception as exc:
                        self.logger.exception("signal reload error: %s", exc)
                        self.db.log_event("ERROR", "CORE_RELOAD", str(exc))

            async def revision_fallback_watcher() -> None:
                while not self.stop_event.is_set():
                    try:
                        latest = self.db.get_revision()
                        if latest != self.revision:
                            await self.perform_reload("fallback_poll")
                    except Exception as exc:
                        self.logger.exception("revision fallback watcher error: %s", exc)
                        self.db.log_event("ERROR", "CORE_WATCHER", str(exc))
                    await asyncio.sleep(max(1, self.config.revision_poll_seconds or 3))

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.stop_event.set)
                except NotImplementedError:
                    pass
            if hasattr(signal, "SIGUSR1"):
                try:
                    loop.add_signal_handler(signal.SIGUSR1, self.reload_event.set)
                except NotImplementedError:
                    pass

            background = [
                asyncio.create_task(signal_reload_watcher()),
                asyncio.create_task(revision_fallback_watcher()),
                asyncio.create_task(client.run_until_disconnected()),
                asyncio.create_task(self.stop_event.wait()),
            ]
            _done, pending = await asyncio.wait(background, return_when=asyncio.FIRST_COMPLETED)
            self.stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.logger.info("core service stopping")
            self.db.log_event("INFO", "CORE", "core service stopping")


async def run(work_dir: Path) -> None:
    app = CoreApp(work_dir)
    await app.run()
