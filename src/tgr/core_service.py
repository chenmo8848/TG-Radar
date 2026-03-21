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
from .telegram_utils import blockquote_preview, build_message_link, bullet, escape, html_code, panel, section
from .version import __version__


@dataclass
class RuntimeState:
    target_map: dict[int, list[dict]]
    valid_rules_count: int
    revision: int
    started_at: datetime


@dataclass
class RuleHit:
    rule_name: str
    total_count: int
    first_hit: str


def severity_label(rule_count: int, total_hits: int) -> tuple[str, str]:
    if rule_count >= 3 or total_hits >= 8:
        return "高优先级", "🔥"
    if rule_count >= 2 or total_hits >= 4:
        return "高关注", "🚨"
    return "常规命中", "⚠️"


def collect_rule_hits(pattern: re.Pattern[str], text: str, max_collect: int = 20) -> tuple[int, str | None]:
    count = 0
    first_hit: str | None = None
    for idx, match in enumerate(pattern.finditer(text)):
        if idx >= max_collect:
            count += 1
            continue
        count += 1
        if first_hit is None:
            first_hit = match.group(0)
    return count, first_hit


def display_sender_name(sender: object | None, fallback: str = "未知用户") -> str:
    if sender is None:
        return fallback
    username = getattr(sender, "username", None)
    if username:
        username = str(username).lstrip("@")
        return f"@{username}"
    first_name = (getattr(sender, "first_name", None) or "").strip()
    last_name = (getattr(sender, "last_name", None) or "").strip()
    full = (first_name + (" " + last_name if last_name else "")).strip()
    return full or fallback


def render_alert_message(*, folder_name: str, chat_title: str, sender_name: str, msg_link: str, msg_text: str, rule_hits: list[RuleHit]) -> str:
    total_hits = sum(item.total_count for item in rule_hits)
    severity, icon = severity_label(len(rule_hits), total_hits)
    detail_rows: list[str] = []
    for item in rule_hits[:4]:
        detail_rows.append(f"· {escape(item.rule_name)}：{html_code(item.first_hit)} × {html_code(item.total_count)}")
    if len(rule_hits) > 4:
        detail_rows.append(f"· 其余规则：{html_code('+' + str(len(rule_hits) - 4))}")
    sections = [
        section("命中摘要", [bullet("等级", severity), bullet("分组", folder_name), bullet("来源", chat_title, code=False), bullet("发送者", sender_name, code=False), bullet("时间", datetime.now().strftime("%m-%d %H:%M:%S"), code=False)]),
        section("命中详情", detail_rows),
        section("消息预览", [blockquote_preview(msg_text, 760)]),
    ]
    footer = f'{icon} <a href="{msg_link}">打开原始消息</a>' if msg_link else f'{icon} <i>当前消息不支持直达链接</i>'
    return panel("TR 管理器 · 命中告警", sections, footer)


def compile_target_map(raw_target_map: dict[int, list[dict]], logger) -> dict[int, list[dict]]:
    compiled: dict[int, list[dict]] = {}
    for chat_id, tasks in raw_target_map.items():
        for task in tasks:
            compiled_rules: list[tuple[str, re.Pattern[str]]] = []
            for rule_name, pattern in task["rules"]:
                try:
                    compiled_rules.append((rule_name, re.compile(pattern, re.IGNORECASE)))
                except re.error as exc:
                    logger.warning("invalid regex skipped: folder=%s rule=%s err=%s", task["folder_name"], rule_name, exc)
            if not compiled_rules:
                continue
            compiled.setdefault(chat_id, []).append({"folder_name": task["folder_name"], "alert_channel": task["alert_channel"], "rules": compiled_rules})
    return compiled


class CoreApp:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.config = load_config(work_dir)
        self.logger = setup_logger("tr-manager-core", self.config.logs_dir / "core.log")
        self.db = RadarDB(self.config.db_path)
        seed_db_from_legacy_config_if_needed(work_dir, self.db)
        self.stop_event = asyncio.Event()
        self.reload_event = asyncio.Event()
        self.plugin_manager = PluginManager(self)
        self.client: TelegramClient | None = None
        self.state: RuntimeState | None = None

    async def reload_runtime_state(self) -> RuntimeState:
        raw_target_map, valid_rules_count = self.db.build_target_map(self.config.global_alert_channel_id)
        compiled = compile_target_map(raw_target_map, self.logger)
        previous = self.state.started_at if self.state else datetime.now()
        self.state = RuntimeState(target_map=compiled, valid_rules_count=valid_rules_count, revision=self.db.get_revision(), started_at=previous)
        return self.state

    async def run(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        if not (self.config.core_session.with_suffix(".session")).exists():
            raise FileNotFoundError("Missing runtime/sessions/tg_radar_core.session. Run bootstrap_session.py first.")
        lock_file = self.work_dir / ".core.lock"
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform != "win32":
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as exc:
            raise RuntimeError("tg-radar-core is already running") from exc
        await self.reload_runtime_state()
        self.plugin_manager.load_core_plugins()
        await self.plugin_manager.run_healthchecks()
        async with TelegramClient(str(self.config.core_session), self.config.api_id, self.config.api_hash) as client:
            self.client = client
            client.parse_mode = "html"
            self.logger.info("core service started, version=%s, revision=%s, chats=%s, rules=%s", __version__, self.state.revision, len(self.state.target_map), self.state.valid_rules_count)
            self.db.log_event("INFO", "CORE", f"TR 管理器 Core 已启动 v{__version__}")

            @client.on(events.NewMessage)
            async def message_handler(event: events.NewMessage.Event) -> None:
                try:
                    await self.plugin_manager.process_core_message(self, event)
                except Exception as exc:
                    self.logger.exception("message handler error: %s", exc)
                    self.db.log_event("ERROR", "CORE_HANDLER", str(exc))

            async def perform_reload(trigger: str) -> None:
                await self.reload_runtime_state()
                self.logger.info("core reloaded trigger=%s revision=%s chats=%s rules=%s", trigger, self.state.revision, len(self.state.target_map), self.state.valid_rules_count)
                await self.plugin_manager.run_healthchecks()
                self.db.log_event("INFO", "CORE_RELOAD", f"trigger={trigger}; revision={self.state.revision}")

            async def signal_reload_watcher() -> None:
                while not self.stop_event.is_set():
                    await self.reload_event.wait()
                    self.reload_event.clear()
                    try:
                        await perform_reload("signal")
                    except Exception as exc:
                        self.logger.exception("signal reload error: %s", exc)
                        self.db.log_event("ERROR", "CORE_RELOAD", str(exc))

            async def revision_fallback_watcher() -> None:
                while not self.stop_event.is_set():
                    try:
                        latest = self.db.get_revision()
                        if latest != self.state.revision:
                            await perform_reload("fallback_poll")
                    except Exception as exc:
                        self.logger.exception("revision fallback watcher error: %s", exc)
                        self.db.log_event("ERROR", "CORE_WATCHER", str(exc))
                    await asyncio.sleep(self.config.revision_poll_seconds or 3)

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
                asyncio.create_task(client.run_until_disconnected()),
                asyncio.create_task(self.stop_event.wait()),
            ]
            if self.config.revision_poll_seconds >= 0:
                background.append(asyncio.create_task(revision_fallback_watcher()))
            _done, pending = await asyncio.wait(set(background), return_when=asyncio.FIRST_COMPLETED)
            self.stop_event.set()
            self.reload_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.logger.info("TR 管理器 Core stopping")
            self.db.log_event("INFO", "CORE", "TR 管理器 Core 正在停止")


async def run(work_dir: Path) -> None:
    app = CoreApp(work_dir)
    await app.run()
