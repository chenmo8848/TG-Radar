from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events

from .compat import seed_db_from_legacy_config_if_needed
from .config import load_config
from .core.plugin_system import PluginManager
from .db import RadarDB
from .logger import setup_logger
from .version import __version__


@dataclass
class RuntimeState:
    target_map: dict[int, list[dict]]
    valid_rules_count: int
    revision: int
    started_at: datetime


def compile_target_map(raw: dict[int, list[dict]], logger) -> dict[int, list[dict]]:
    compiled: dict[int, list[dict]] = {}
    for chat_id, tasks in raw.items():
        for task in tasks:
            rules = []
            for rule_name, pattern in task["rules"]:
                try:
                    rules.append((rule_name, re.compile(pattern, re.IGNORECASE)))
                except re.error as exc:
                    logger.warning("正则无效 folder=%s rule=%s: %s", task["folder_name"], rule_name, exc)
            if rules:
                compiled.setdefault(chat_id, []).append({"folder_name": task["folder_name"], "alert_channel": task["alert_channel"], "rules": rules})
    return compiled


class CoreApp:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.config = load_config(work_dir)
        self.logger = setup_logger("tg-radar-core", self.config.logs_dir / "core.log")
        self.db = RadarDB(self.config.db_path)
        seed_db_from_legacy_config_if_needed(work_dir, self.db)
        self.stop_event = asyncio.Event()
        self.reload_event = asyncio.Event()
        self.plugin_manager = PluginManager(self)
        self.client: TelegramClient | None = None
        self.state: RuntimeState | None = None

    async def reload_runtime_state(self) -> RuntimeState:
        raw, count = self.db.build_target_map(self.config.global_alert_channel_id)
        compiled = compile_target_map(raw, self.logger)
        prev = self.state.started_at if self.state else datetime.now()
        self.state = RuntimeState(target_map=compiled, valid_rules_count=count, revision=self.db.get_revision(), started_at=prev)
        return self.state

    async def run(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.core_session.with_suffix(".session").exists():
            raise FileNotFoundError("缺少 core session，请执行 TR reauth")
        lock_file = self.work_dir / ".core.lock"
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform != "win32":
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as exc:
            raise RuntimeError("Core 进程已在运行中") from exc

        pid_file = self.config.runtime_dir / "core.pid"
        pid_file.write_text(str(os.getpid()))

        await self.reload_runtime_state()
        self.plugin_manager.load_core_plugins()
        await self.plugin_manager.run_healthchecks()

        async with TelegramClient(str(self.config.core_session), self.config.api_id, self.config.api_hash) as client:
            self.client = client
            client.parse_mode = "html"
            self.logger.info("Core 已启动 v%s | revision=%s chats=%s rules=%s", __version__, self.state.revision, len(self.state.target_map), self.state.valid_rules_count)
            self.db.log_event("INFO", "CORE", f"Core 已启动 v{__version__}")

            @client.on(events.NewMessage)
            async def on_message(event) -> None:
                try:
                    await self.plugin_manager.process_core_message(self, event)
                except Exception as exc:
                    self.logger.exception("消息处理异常: %s", exc)
                    self.db.log_event("ERROR", "CORE_HANDLER", str(exc))

            async def do_reload(trigger: str) -> None:
                await self.reload_runtime_state()
                self.logger.info("Core 重载 trigger=%s revision=%s chats=%s rules=%s", trigger, self.state.revision, len(self.state.target_map), self.state.valid_rules_count)
                await self.plugin_manager.run_healthchecks()
                self.db.log_event("INFO", "CORE_RELOAD", f"trigger={trigger}; revision={self.state.revision}")

            async def signal_watcher() -> None:
                while not self.stop_event.is_set():
                    await self.reload_event.wait()
                    self.reload_event.clear()
                    try:
                        await do_reload("signal")
                    except Exception as exc:
                        self.logger.exception("信号重载异常: %s", exc)

            async def revision_watcher() -> None:
                interval = self.config.revision_poll_seconds
                while not self.stop_event.is_set():
                    try:
                        if self.db.get_revision() != self.state.revision:
                            await do_reload("poll")
                    except Exception as exc:
                        self.logger.exception("轮询重载异常: %s", exc)
                    await asyncio.sleep(interval)

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

            bg = [asyncio.create_task(signal_watcher()), asyncio.create_task(client.run_until_disconnected()), asyncio.create_task(self.stop_event.wait())]
            if self.config.revision_poll_seconds > 0:
                bg.append(asyncio.create_task(revision_watcher()))
            _, pending = await asyncio.wait(set(bg), return_when=asyncio.FIRST_COMPLETED)
            self.stop_event.set()
            self.reload_event.set()
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.logger.info("Core 正在关闭")
            self.db.log_event("INFO", "CORE", "Core 正在关闭")
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass


async def run(work_dir: Path) -> None:
    await CoreApp(work_dir).run()
