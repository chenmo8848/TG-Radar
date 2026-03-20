from __future__ import annotations

import asyncio
import html
import json
import os
import re
import shlex
import signal
import subprocess
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events, functions, types, utils

from .compat import seed_db_from_legacy_config_if_needed
from .config import load_config, sync_snapshot_to_config, update_config_data
from .db import RadarDB, RouteTask
from .logger import setup_logger
from .sync_logic import RouteReport, SyncReport, scan_auto_routes, sync_dialog_folders
from .telegram_utils import dialog_filter_title, format_duration, normalize_pattern_from_terms, try_remove_terms_from_pattern
from .version import __version__


class AdminApp:
    def __init__(self, work_dir: Path) -> None:
        self.config = load_config(work_dir)
        self.logger = setup_logger("tg-radar-admin", self.config.logs_dir / "admin.log")
        self.db = RadarDB(self.config.db_path)
        seed_db_from_legacy_config_if_needed(work_dir, self.db)
        sync_snapshot_to_config(work_dir, self.db)
        self.started_at = datetime.now()
        self.stop_event = asyncio.Event()
        self.sync_lock = asyncio.Lock()
        self.client: TelegramClient | None = None

    async def run(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        if not (self.config.admin_session.with_suffix(".session")).exists():
            raise FileNotFoundError("Missing runtime/sessions/tg_radar_admin.session. Run bootstrap_session.py first.")

        lock_file = self.config.work_dir / ".admin.lock"
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        try:
            if os.name != "nt":
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            raise RuntimeError("tg-radar-admin is already running")

        async with TelegramClient(str(self.config.admin_session), self.config.api_id, self.config.api_hash) as client:
            self.client = client
            client.parse_mode = "html"
            self.register_handlers(client)
            self.db.log_event("INFO", "ADMIN", f"TG-Radar admin started v{__version__}")
            await self.send_startup_notification()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.stop_event.set)
                except NotImplementedError:
                    pass

            tasks = [
                asyncio.create_task(self.periodic_sync()),
                asyncio.create_task(self.route_worker()),
                asyncio.create_task(client.run_until_disconnected()),
                asyncio.create_task(self.stop_event.wait()),
            ]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            self.stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.db.log_event("INFO", "ADMIN", "admin service stopping")
            self.logger.info("TG-Radar admin service stopping")

    def register_handlers(self, client: TelegramClient) -> None:
        prefix = self.config.cmd_prefix
        cmd_regex = re.compile(rf"^{re.escape(prefix)}(\w+)[ \t]*([\s\S]*)", re.IGNORECASE)

        @client.on(events.NewMessage(chats=["me"], pattern=cmd_regex))
        async def control_panel(event: events.NewMessage.Event) -> None:
            command = event.pattern_match.group(1).lower()
            args = (event.pattern_match.group(2) or "").strip()
            try:
                await self.dispatch(event, command, args)
            except Exception as exc:
                self.logger.exception("command failed: %s", exc)
                self.db.log_event("ERROR", "COMMAND", str(exc))
                await self.safe_reply(
                    event,
                    f"❌ <b>TG-Radar 命令执行异常</b>\n"
                    f"<blockquote expandable>{html.escape(str(exc))}</blockquote>\n"
                    f"<i>已写入运行日志，可稍后在终端执行 <code>TR logs admin</code> 排查。</i>",
                )

    async def dispatch(self, event: events.NewMessage.Event, command: str, args: str) -> None:
        prefix = html.escape(self.config.cmd_prefix)

        if command == "help":
            await self.safe_reply(event, self.render_help_message(), auto_delete=max(60, self.config.panel_auto_delete_seconds))
            return

        if command == "ping":
            stats = self.db.get_runtime_stats()
            await self.safe_reply(
                event,
                "⚡ <b>TG-Radar 在线</b>\n"
                f"· 管理层运行：<code>{html.escape(format_duration((datetime.now() - self.started_at).total_seconds()))}</code>\n"
                f"· 历史命中：<code>{html.escape(stats.get('total_hits', '0'))}</code>\n"
                f"· 热更新轮询：<code>{self.config.revision_poll_seconds} 秒</code>\n"
                f"· 自动同步轮询：<code>{self.config.sync_interval_seconds} 秒</code>",
                auto_delete=12,
            )
            return

        if command == "status":
            await self.safe_reply(event, self.render_status_message())
            return

        if command == "version":
            await self.safe_reply(
                event,
                f"🧩 <b>TG-Radar 版本信息</b>\n\n"
                f"· 版本：<code>{__version__}</code>\n"
                f"· 架构：<code>Plan C · Admin + Core · SQLite WAL</code>\n"
                f"· 全局命令：<code>TR</code>\n"
                f"· 工作目录：<code>{html.escape(str(self.config.work_dir))}</code>\n"
                f"· 会话回收：<code>编辑原消息 + 自动回收面板</code>",
            )
            return

        if command == "config":
            await self.safe_reply(event, self.render_config_message())
            return

        if command == "setnotify":
            value = self.parse_int_or_none(args)
            update_config_data(self.config.work_dir, {"notify_channel_id": value})
            self.config = load_config(self.config.work_dir)
            self.db.log_event("INFO", "SET_NOTIFY", str(value))
            await self.safe_reply(
                event,
                f"✅ <b>系统通知目标已更新</b>\n"
                f"· 新目标：<code>{value if value is not None else 'Saved Messages'}</code>\n"
                f"· 说明：启动通知、自动同步报告、升级提示都会发往这里。",
            )
            return

        if command == "setalert":
            value = self.parse_int_or_none(args)
            update_config_data(self.config.work_dir, {"global_alert_channel_id": value})
            self.config = load_config(self.config.work_dir)
            self.db.log_event("INFO", "SET_ALERT", str(value))
            await self.safe_reply(
                event,
                f"✅ <b>默认告警频道已更新</b>\n"
                f"· 新目标：<code>{value if value is not None else '未设置'}</code>\n"
                f"· 说明：未单独指定 alert_channel 的分组会走这里。",
            )
            return

        if command == "setprefix":
            value = args.strip()
            if not value or len(value) > 3 or " " in value or any(ch in value for ch in ["\", """, "'"]):
                await self.safe_reply(event, "⚠️ <b>前缀格式无效</b>\n建议使用 1-3 个字符，且不能包含空格、引号或反斜杠。")
                return
            update_config_data(self.config.work_dir, {"cmd_prefix": value})
            self.db.log_event("INFO", "SET_PREFIX", value)
            self.write_last_message(event.id, "restart")
            await self.safe_reply(
                event,
                f"✅ <b>命令前缀已更新</b>\n"
                f"· 新前缀：<code>{html.escape(value)}</code>\n"
                f"· 后续使用：<code>{html.escape(value)}help</code>\n\n"
                f"<i>即将重启双服务并加载新前缀。</i>",
                auto_delete=0,
            )
            self.restart_services(delay=1.2)
            return

        if command == "log":
            limit = 30
            if args.isdigit():
                limit = min(200, max(1, int(args)))
            rows = self.db.recent_logs(limit)
            if not rows:
                await self.safe_reply(event, "📋 <b>当前还没有可展示的运行日志</b>")
                return
            body = "\n".join(f"[{row['created_at']}] {row['level']}/{row['action']} :: {row['detail']}" for row in rows)
            await self.safe_reply(event, f"📋 <b>最近 {len(rows)} 条运行日志</b>\n<blockquote expandable>{html.escape(body)}</blockquote>", auto_delete=max(90, self.config.panel_auto_delete_seconds))
            return

        if command == "folders":
            rows = self.db.list_folders()
            if not rows:
                await self.safe_reply(event, "📂 <b>当前还没有任何分组记录</b>\n<i>先执行一次同步，或者手动在 Telegram 侧创建分组后再试。</i>")
                return
            blocks = []
            for row in rows:
                folder_name = row["folder_name"]
                group_count = self.db.count_cache_for_folder(folder_name)
                rule_count = self.db.count_rules_for_folder(folder_name)
                icon = "🟢" if int(row["enabled"]) == 1 else "⚪"
                blocks.append(
                    f"{icon} <b>{html.escape(folder_name)}</b>\n"
                    f"  ├ 监听状态：<code>{'开启' if int(row['enabled']) == 1 else '关闭'}</code>\n"
                    f"  ├ 收纳群数：<code>{group_count}</code>\n"
                    f"  └ 规则数量：<code>{rule_count}</code>"
                )
            await self.safe_reply(event, f"📂 <b>TG 分组总览</b>\n\n" + "\n\n".join(blocks), auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command == "rules":
            if not args:
                await self.safe_reply(event, f"⚠️ <b>请指定分组名</b>\n示例：<code>{prefix}rules 业务群</code>")
                return
            folder = self.find_folder(args)
            if folder is None:
                await self.safe_reply(event, "⚠️ <b>找不到该分组</b>\n<i>可以先发送 folders 查看系统当前识别到的分组。</i>")
                return
            rows = self.db.get_rules_for_folder(folder)
            if not rows:
                body = "<i>该分组还没有监控规则</i>"
            else:
                body = "\n\n".join(
                    f"<b>{html.escape(row['rule_name'])}</b>\n<code>{html.escape(row['pattern'])}</code>" for row in rows
                )
            await self.safe_reply(event, f"🛡️ <b>{html.escape(folder)} · 规则面板</b>\n<blockquote>{body}</blockquote>", auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command in {"enable", "disable"}:
            if not args:
                await self.safe_reply(event, f"⚠️ <b>请指定分组名</b>\n示例：<code>{prefix}{command} 业务群</code>")
                return
            folder = self.find_folder(args)
            if folder is None:
                await self.safe_reply(event, "⚠️ <b>找不到该分组</b>")
                return
            self.db.set_folder_enabled(folder, command == "enable")
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "TOGGLE_FOLDER", f"{folder} -> {command}")
            word = "开启" if command == "enable" else "关闭"
            await self.safe_reply(
                event,
                f"✅ <b>分组状态已更新</b>\n"
                f"· 分组：<code>{html.escape(folder)}</code>\n"
                f"· 当前状态：<code>{word}</code>\n"
                f"· 生效方式：<code>即时热更新，无需重启</code>",
            )
            return

        if command == "addrule":
            tokens = shlex.split(args)
            if len(tokens) < 3:
                await self.safe_reply(event, f"⚠️ <b>参数不足</b>\n示例：<code>{prefix}addrule 业务群 核心词 苹果 华为</code>")
                return
            folder = self.find_folder(tokens[0])
            if folder is None:
                await self.safe_reply(event, "⚠️ <b>找不到该分组</b>")
                return
            rule_name = tokens[1]
            pattern = normalize_pattern_from_terms(" ".join(tokens[2:]))
            self.db.upsert_rule(folder, rule_name, pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "ADD_RULE", f"{folder}/{rule_name} -> {pattern}")
            await self.safe_reply(
                event,
                f"✅ <b>规则已保存</b>\n"
                f"· 分组：<code>{html.escape(folder)}</code>\n"
                f"· 规则名：<code>{html.escape(rule_name)}</code>\n"
                f"· 匹配式：<code>{html.escape(pattern)}</code>\n"
                f"· 生效方式：<code>即时热更新</code>",
            )
            return

        if command == "delrule":
            tokens = shlex.split(args)
            if len(tokens) < 2:
                await self.safe_reply(event, f"⚠️ <b>参数不足</b>\n示例：<code>{prefix}delrule 业务群 核心词 [要删的词]</code>")
                return
            folder = self.find_folder(tokens[0])
            if folder is None:
                await self.safe_reply(event, "⚠️ <b>找不到该分组</b>")
                return
            rule_name = tokens[1]
            if len(tokens) == 2:
                if not self.db.delete_rule(folder, rule_name):
                    await self.safe_reply(event, "⚠️ <b>没有找到这条规则</b>")
                    return
                sync_snapshot_to_config(self.config.work_dir, self.db)
                self.db.log_event("INFO", "DELETE_RULE", f"{folder}/{rule_name}")
                await self.safe_reply(event, f"🗑️ <b>规则已删除</b>\n· 分组：<code>{html.escape(folder)}</code>\n· 规则名：<code>{html.escape(rule_name)}</code>")
                return
            current_rows = self.db.get_rules_for_folder(folder)
            current = next((row for row in current_rows if row["rule_name"] == rule_name), None)
            if current is None:
                await self.safe_reply(event, "⚠️ <b>没有找到这条规则</b>")
                return
            new_pattern = try_remove_terms_from_pattern(str(current["pattern"]), tokens[2:])
            if new_pattern is None:
                self.db.delete_rule(folder, rule_name)
                sync_snapshot_to_config(self.config.work_dir, self.db)
                self.db.log_event("INFO", "DELETE_RULE", f"{folder}/{rule_name} -> removed all terms")
                await self.safe_reply(event, f"🗑️ <b>规则已整体删除</b>\n· 分组：<code>{html.escape(folder)}</code>\n· 规则名：<code>{html.escape(rule_name)}</code>")
                return
            self.db.update_rule_pattern(folder, rule_name, new_pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "UPDATE_RULE", f"{folder}/{rule_name} -> {new_pattern}")
            await self.safe_reply(event, f"✅ <b>规则已更新</b>\n· 新表达式：<code>{html.escape(new_pattern)}</code>")
            return

        if command == "routes":
            rows = self.db.list_routes()
            if not rows:
                await self.safe_reply(event, "🔀 <b>当前没有自动收纳规则</b>")
                return
            body = "\n\n".join(
                f"<b>{html.escape(row['folder_name'])}</b>\n<code>{html.escape(row['pattern'])}</code>" for row in rows
            )
            await self.safe_reply(event, f"🔀 <b>自动收纳规则面板</b>\n<blockquote>{body}</blockquote>", auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command == "addroute":
            tokens = shlex.split(args)
            if len(tokens) < 2:
                await self.safe_reply(event, f"⚠️ <b>参数不足</b>\n示例：<code>{prefix}addroute 业务群 供需 担保</code>")
                return
            folder = self.find_folder(tokens[0]) or tokens[0]
            if self.db.get_folder(folder) is None:
                self.db.upsert_folder(folder, None, enabled=False)
                self.db.upsert_rule(folder, f"{folder}监控", "(示范词A|示范词B)")
            pattern = normalize_pattern_from_terms(" ".join(tokens[1:]))
            self.db.set_route(folder, pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "ADD_ROUTE", f"{folder} -> {pattern}")
            await self.safe_reply(
                event,
                f"✅ <b>自动收纳规则已保存</b>\n"
                f"· 分组：<code>{html.escape(folder)}</code>\n"
                f"· 路由规则：<code>{html.escape(pattern)}</code>\n"
                f"· 说明：后续自动同步会持续检查并把匹配的新群排队补入该分组。",
            )
            return

        if command == "delroute":
            if not args:
                await self.safe_reply(event, f"⚠️ <b>参数不足</b>\n示例：<code>{prefix}delroute 业务群</code>")
                return
            folder = self.find_folder(args) or args.strip()
            if not self.db.delete_route(folder):
                await self.safe_reply(event, "⚠️ <b>没有找到该自动收纳规则</b>")
                return
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "DELETE_ROUTE", folder)
            await self.safe_reply(event, f"🗑️ <b>自动收纳规则已删除</b>\n· 分组：<code>{html.escape(folder)}</code>")
            return

        if command == "sync":
            await self.run_sync_command(event)
            return

        if command == "restart":
            self.write_last_message(event.id, "restart")
            await self.safe_reply(
                event,
                "🔄 <b>TG-Radar 即将重启</b>\n"
                "· Admin / Core 会一起重启\n"
                "· 数据库中的未完成路由任务会被保留\n"
                "· 重启后系统会自动接管未完成任务",
                auto_delete=0,
            )
            self.db.log_event("INFO", "RESTART", "restart requested from Telegram")
            self.restart_services(delay=1.2)
            return

        if command == "update":
            self.write_last_message(event.id, "update")
            await self.run_update_command(event)
            return

        await self.safe_reply(event, f"⚠️ <b>未知命令</b>\n请发送 <code>{prefix}help</code> 查看可用指令。")

    async def run_sync_command(self, event: events.NewMessage.Event) -> None:
        if self.sync_lock.locked():
            await self.safe_reply(event, "⚠️ <b>系统正忙</b>\n后台正在执行其他同步任务，请稍等一两秒后再试。")
            return
        async with self.sync_lock:
            await self.safe_reply(
                event,
                "⏳ <b>正在执行全量同步</b>\n"
                "· 比对 Telegram 分组拓扑\n"
                "· 回写缓存与规则快照\n"
                "· 扫描自动收纳并补充队列\n"
                "· 命中配置通过 revision 立即热更新",
                auto_delete=0,
            )
            sync_report = await sync_dialog_folders(self.client, self.db)
            route_report = await scan_auto_routes(self.client, self.db)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "SYNC", f"sync changed={sync_report.has_changes} queued={sum(route_report.queued.values())}")
            await self.safe_reply(event, self.render_sync_message(sync_report, route_report), auto_delete=max(55, self.config.panel_auto_delete_seconds))

    async def run_update_command(self, event: events.NewMessage.Event) -> None:
        if not (self.config.work_dir / ".git").exists():
            await self.safe_reply(event, "⚠️ <b>当前目录不是 git 仓库</b>\n请用 git 方式部署后再执行 update。")
            return
        await self.safe_reply(event, "🔄 <b>正在执行 git pull --ff-only</b>\n<i>更新完成后会自动重启双服务。</i>", auto_delete=0)
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(self.config.work_dir), "pull", "--ff-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = (stdout or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            self.db.log_event("ERROR", "UPDATE", output or f"git pull failed: {proc.returncode}")
            await self.safe_reply(event, f"❌ <b>代码更新失败</b>\n<blockquote expandable>{html.escape(output or 'git pull failed')}</blockquote>")
            return
        self.db.log_event("INFO", "UPDATE", output or "git pull ok")
        await self.safe_reply(
            event,
            f"✅ <b>代码更新完成</b>\n"
            f"<blockquote expandable>{html.escape(output or 'Already up to date.')}</blockquote>\n"
            f"<i>即将重启 Admin / Core 以加载新版本。</i>",
            auto_delete=0,
        )
        self.restart_services(delay=1.5)

    async def periodic_sync(self) -> None:
        await asyncio.sleep(5)
        while not self.stop_event.is_set():
            if not self.sync_lock.locked():
                try:
                    async with self.sync_lock:
                        sync_report = await sync_dialog_folders(self.client, self.db)
                        route_report = await scan_auto_routes(self.client, self.db)
                        sync_snapshot_to_config(self.config.work_dir, self.db)
                        self.db.log_event("INFO", "AUTO_SYNC", f"sync changed={sync_report.has_changes} queued={sum(route_report.queued.values())}")
                        if sync_report.has_changes or route_report.queued or route_report.created:
                            await self.send_sync_report(sync_report, route_report, automatic=True)
                except Exception as exc:
                    self.logger.exception("periodic sync failed: %s", exc)
                    self.db.log_event("ERROR", "AUTO_SYNC", str(exc))
            await asyncio.sleep(self.config.sync_interval_seconds)

    async def route_worker(self) -> None:
        while not self.stop_event.is_set():
            task = self.db.get_next_route_task()
            if task is None:
                await asyncio.sleep(2)
                continue
            try:
                await self.apply_route_task(task)
                self.db.complete_route_task(task.id)
                self.db.log_event("INFO", "ROUTE_TASK", f"{task.folder_name} +{len(task.peer_ids)}")
                sync_snapshot_to_config(self.config.work_dir, self.db)
            except Exception as exc:
                self.logger.exception("route task failed: %s", exc)
                retry = task.retries < 3
                self.db.fail_route_task(task.id, str(exc), retry=retry)
                self.db.log_event("ERROR", "ROUTE_TASK", f"{task.folder_name}: {exc}")
            await asyncio.sleep(self.config.route_worker_interval_seconds)

    async def apply_route_task(self, task: RouteTask) -> None:
        assert self.client is not None
        req = await self.client(functions.messages.GetDialogFiltersRequest())
        folders = [f for f in getattr(req, "filters", []) if isinstance(f, types.DialogFilter)]
        target = None
        for folder in folders:
            title = dialog_filter_title(folder)
            if (task.folder_id is not None and int(folder.id) == int(task.folder_id)) or title == task.folder_name:
                target = folder
                break

        peers = []
        for peer_id in task.peer_ids:
            try:
                peers.append(await self.client.get_input_entity(peer_id))
            except Exception:
                continue
        if not peers:
            return

        if target is None:
            folder_id = task.folder_id or 2
            used_ids = {int(f.id) for f in folders}
            while folder_id in used_ids:
                folder_id += 1
            new_filter = types.DialogFilter(
                id=folder_id,
                title=task.folder_name,
                pinned_peers=[],
                include_peers=peers[:100],
                exclude_peers=[],
                contacts=False,
                non_contacts=False,
                groups=False,
                broadcasts=False,
                bots=False,
                exclude_muted=False,
                exclude_read=False,
                exclude_archived=False,
            )
            await self.client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=new_filter))
            self.db.upsert_folder(task.folder_name, folder_id)
            return

        current_ids = set()
        for peer in getattr(target, "include_peers", []):
            try:
                current_ids.add(int(utils.get_peer_id(peer)))
            except Exception:
                continue
        existing = list(getattr(target, "include_peers", []))
        for peer in peers:
            try:
                pid = int(utils.get_peer_id(peer))
            except Exception:
                continue
            if pid in current_ids:
                continue
            existing.append(peer)
            current_ids.add(pid)
            if len(existing) >= 100:
                break
        target.include_peers = existing[:100]
        await self.client(functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target))

    async def send_sync_report(self, sync_report: SyncReport, route_report: RouteReport, automatic: bool = False) -> None:
        assert self.client is not None
        target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "me"
        title = "🔄 <b>TG-Radar 自动同步报告</b>" if automatic else "🔄 <b>TG-Radar 手动同步报告</b>"
        lines = [title, ""]
        status = "发现变动并已更新" if sync_report.has_changes or route_report.queued or route_report.created else "同步完成，数据无变动"
        lines += [
            "<b>⚙️ 执行摘要</b>",
            f"· 结果：<code>{status}</code>",
            f"· 耗时：<code>{sync_report.elapsed_seconds:.1f} 秒</code>",
            f"· 时间：<code>{datetime.now().strftime('%m-%d %H:%M:%S')}</code>",
            "",
            "<b>📂 分组变动详情</b>",
        ]
        if sync_report.discovered:
            lines += [f"· ✨ 新分组：<code>{html.escape(name)}</code>" for name in sync_report.discovered]
        if sync_report.renamed:
            lines += [f"· 🔄 已改名：<code>{html.escape(old)}</code> → <code>{html.escape(new)}</code>" for old, new in sync_report.renamed]
        if sync_report.deleted:
            lines += [f"· 🗑️ 已删除：<code>{html.escape(name)}</code>" for name in sync_report.deleted]
        if not (sync_report.discovered or sync_report.renamed or sync_report.deleted):
            lines.append("· <i>本次没有新增、改名或删除任何分组</i>")

        lines += ["", "<b>🔀 自动收纳扫描</b>"]
        if route_report.created or route_report.queued or route_report.matched_zero or route_report.already_in or route_report.errors:
            for name in route_report.created:
                lines.append(f"· ✨ 自动新建分组：<code>{html.escape(name)}</code>")
            for name, cnt in route_report.queued.items():
                lines.append(f"· ⏳ 已排队补群：<code>{html.escape(name)}</code> + <code>{cnt}</code>")
            for name, cnt in route_report.already_in.items():
                lines.append(f"· 📦 已在分组内：<code>{html.escape(name)}</code> · <code>{cnt}</code>")
            for name in route_report.matched_zero:
                lines.append(f"· 🔕 未匹配到任何群：<code>{html.escape(name)}</code>")
            for name, err in route_report.errors.items():
                lines.append(f"· ❌ {html.escape(name)}：{html.escape(err)}")
        else:
            lines.append("· <i>本次没有新增自动收纳动作</i>")

        lines += ["", "<b>🌐 当前分组规模</b>"]
        if sync_report.active:
            for name, cnt in sync_report.active.items():
                lines.append(f"· 🟢 <b>{html.escape(name)}</b> · <code>{cnt}</code> 个群")
        else:
            lines.append("· <i>当前没有读取到任何分组群数据</i>")
        lines += ["", f"💡 <i>发现新分组后，记得发送 <code>{html.escape(self.config.cmd_prefix)}enable [分组名]</code> 开启监控。</i>"]
        try:
            msg = await self.client.send_message(target, "\n".join(lines), link_preview=False)
            if msg and self.config.notify_auto_delete_seconds > 0:
                asyncio.create_task(self.delete_later(msg, self.config.notify_auto_delete_seconds))
        except Exception as exc:
            self.logger.warning("send sync report failed: %s", exc)

    async def send_startup_notification(self) -> None:
        assert self.client is not None
        rows = self.db.list_folders()
        enabled = [row for row in rows if int(row["enabled"]) == 1]
        folder_lines = []
        for row in enabled:
            folder_name = row["folder_name"]
            folder_lines.append(
                f"🟢 <b>{html.escape(folder_name)}</b> · {self.db.count_cache_for_folder(folder_name)} 个群 · {self.db.count_rules_for_folder(folder_name)} 条规则"
            )
        folder_block = "\n".join(folder_lines) if folder_lines else "<i>当前没有开启任何分组监控</i>"
        route_rows = self.db.list_routes()
        route_block = "\n".join(
            f"🔀 <code>{html.escape(row['pattern'])}</code> → <code>{html.escape(row['folder_name'])}</code>"
            for row in route_rows
        ) if route_rows else "<i>当前没有自动收纳规则</i>"

        target_map, valid_rules = self.db.build_target_map(self.config.global_alert_channel_id)
        msg = f"""📡 <b>TG-Radar 已上线</b>

<b>⚙️ 运行概况</b>
· 架构：<code>Admin + Core / SQLite WAL</code>
· 启动时间：<code>{self.started_at.strftime('%Y-%m-%d %H:%M:%S')}</code>
· 自动同步：<code>每 {self.config.sync_interval_seconds} 秒</code>
· 热更新轮询：<code>每 {self.config.revision_poll_seconds} 秒</code>
· 版本：<code>{__version__}</code>

<b>🌐 当前规模</b>
· 活跃分组：<code>{len(enabled)}</code> / <code>{len(rows)}</code>
· 正在监听：<code>{len(target_map)}</code> 个群 / 频道
· 生效规则：<code>{valid_rules}</code> 条

<b>[ 已启用的监控分组 ]</b>
<blockquote>{folder_block}</blockquote>

<b>[ 自动收纳规则 ]</b>
<blockquote>{route_block}</blockquote>

💡 <i>在收藏夹发送 <code>{html.escape(self.config.cmd_prefix)}help</code> 可以打开完整管理菜单。</i>"""

        last_msg_path = self.config.work_dir / ".last_msg"
        target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "me"
        msg_obj = None

        if last_msg_path.exists():
            try:
                ctx = json.loads(last_msg_path.read_text(encoding="utf-8"))
                action = ctx.get("action", "restart")
                prefix_text = "✨ <b>[ 代码更新完毕 ]</b> 系统已加载最新版本。\n\n" if action == "update" else "🔄 <b>[ 重启任务完毕 ]</b> 系统已经恢复。\n\n"
                msg_obj = await self.client.edit_message("me", int(ctx["msg_id"]), prefix_text + msg)
                last_msg_path.unlink(missing_ok=True)
                self.db.log_event("INFO", "RESTORE", f"system back online after {action}")
            except Exception:
                pass

        if msg_obj is None:
            try:
                msg_obj = await self.client.send_message(target, msg, link_preview=False)
            except Exception as exc:
                self.logger.warning("startup notification failed: %s", exc)

        if msg_obj and self.config.notify_auto_delete_seconds > 0:
            asyncio.create_task(self.delete_later(msg_obj, self.config.notify_auto_delete_seconds))

    async def delete_later(self, msg, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass

    async def safe_reply(
        self,
        event: events.NewMessage.Event,
        text: str,
        auto_delete: int | None = None,
        prefer_edit: bool = True,
        recycle_source_on_reply: bool = True,
    ) -> None:
        delete_after = self.config.panel_auto_delete_seconds if auto_delete is None else auto_delete
        msg = None
        edited_original = False

        if prefer_edit:
            try:
                if getattr(event, "out", False):
                    msg = await event.edit(text)
                    edited_original = True
            except Exception:
                msg = None

        if msg is None:
            try:
                msg = await event.reply(text)
            except Exception:
                return

        if msg and delete_after > 0:
            asyncio.create_task(self.delete_later(msg, delete_after))

        if msg is not None and not edited_original and recycle_source_on_reply and self.config.recycle_fallback_command_seconds > 0:
            try:
                asyncio.create_task(self.delete_later(event.message, self.config.recycle_fallback_command_seconds))
            except Exception:
                pass

    def render_help_message(self) -> str:
        prefix = html.escape(self.config.cmd_prefix)
        return f"""🧭 <b>TG-Radar Command Center</b>
<i>所有命令都在 Telegram 收藏夹执行。默认会优先编辑你刚发出的命令消息，并在设定时间后自动回收面板，避免聊天记录堆满垃圾消息。</i>

<b>📊 运行状态</b>
<code>{prefix}status</code>  — 详细运行大屏
<code>{prefix}ping</code>    — 快速心跳测试
<code>{prefix}log 30</code>  — 最近运行日志
<code>{prefix}version</code> — 当前版本 / 架构信息
<code>{prefix}config</code>  — 关键配置总览

<b>📂 分组管理</b>
<code>{prefix}folders</code>              — 查看全部 TG 分组与当前监听规模
<code>{prefix}rules [分组名]</code>       — 查看指定分组的规则清单
<code>{prefix}enable [分组名]</code>      — 开启该分组监控
<code>{prefix}disable [分组名]</code>     — 关闭该分组监控

<b>🛡️ 规则管理</b>
<code>{prefix}addrule [分组] [规则名] [关键词...]</code>
<code>{prefix}delrule [分组] [规则名]</code>
<code>{prefix}delrule [分组] [规则名] [要删的词...]</code>

<b>🔀 自动收纳</b>
<code>{prefix}routes</code>                  — 查看自动收纳规则
<code>{prefix}addroute [分组] [匹配词...]</code>
<code>{prefix}delroute [分组]</code>

<b>🔧 系统维护</b>
<code>{prefix}sync</code>                  — 强制执行一次全盘同步
<code>{prefix}setnotify [ID/off]</code>    — 设置系统通知频道
<code>{prefix}setalert [ID/off]</code>     — 设置默认告警频道
<code>{prefix}setprefix [新前缀]</code>     — 修改命令前缀并自动重启
<code>{prefix}update</code>                — git pull 更新后重启
<code>{prefix}restart</code>               — 直接重启双服务

<b>💡 交互说明</b>
· 面板模式：优先编辑原命令消息，像 PagerMaid 一样减少消息堆积
· 自动回收：帮助面板 / 状态面板 / 同步结果会在后台自动回收
· 即时热更：规则、开关、缓存变动会通过 revision watcher 即时生效"""

    def render_config_message(self) -> str:
        notify_target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "Saved Messages"
        alert_target = self.config.global_alert_channel_id if self.config.global_alert_channel_id is not None else "未设置"
        return f"""🧾 <b>TG-Radar 关键配置</b>

<b>通信与路由</b>
· API_ID：<code>{self.config.api_id}</code>
· 默认告警频道：<code>{alert_target}</code>
· 系统通知频道：<code>{notify_target}</code>
· 命令前缀：<code>{html.escape(self.config.cmd_prefix)}</code>

<b>运行与回收</b>
· 自动同步轮询：<code>{self.config.sync_interval_seconds} 秒</code>
· 热更新轮询：<code>{self.config.revision_poll_seconds} 秒</code>
· 路由队列节流：<code>{self.config.route_worker_interval_seconds} 秒</code>
· 面板自动回收：<code>{self.config.panel_auto_delete_seconds} 秒</code>
· 通知自动回收：<code>{self.config.notify_auto_delete_seconds} 秒</code>

<b>部署信息</b>
· 服务前缀：<code>{html.escape(self.config.service_name_prefix)}</code>
· 全局命令：<code>TR</code>
· 工作目录：<code>{html.escape(str(self.config.work_dir))}</code>
· 仓库地址：<code>{html.escape(self.config.repo_url or '未设置')}</code>"""

    def render_status_message(self) -> str:
        stats = self.db.get_runtime_stats()
        last_folder = stats.get("last_hit_folder") or "暂无记录"
        last_time = stats.get("last_hit_time") or "暂无记录"
        rows = self.db.list_folders()
        enabled_cnt = sum(1 for row in rows if int(row["enabled"]) == 1)
        target_map, valid_rules = self.db.build_target_map(self.config.global_alert_channel_id)
        queue_size = self.db.pending_route_count()
        active_rows = []
        for row in rows[:10]:
            if int(row["enabled"]) != 1:
                continue
            folder_name = row["folder_name"]
            active_rows.append(
                f"· {html.escape(folder_name)} — 群 <code>{self.db.count_cache_for_folder(folder_name)}</code> · 规则 <code>{self.db.count_rules_for_folder(folder_name)}</code>"
            )
        active_block = "\n".join(active_rows) if active_rows else "· <i>暂无启用分组</i>"
        q_info = f"{queue_size} 个任务待补充" if queue_size > 0 else "空闲"
        return f"""📊 <b>TG-Radar 详细监控大屏</b>

<b>⚙️ 运行状态</b>
· 系统状态：<code>🟢 稳定运行中</code>
· 持续运行：<code>{html.escape(format_duration((datetime.now() - self.started_at).total_seconds()))}</code>
· 自动同步：<code>{self.config.sync_interval_seconds} 秒</code>
· 热更新轮询：<code>{self.config.revision_poll_seconds} 秒</code>
· 路由队列：<code>{html.escape(q_info)}</code>

<b>🌐 监控规模</b>
· 活跃分组：<code>{enabled_cnt}</code> / <code>{len(rows)}</code>
· 监听目标：<code>{len(target_map)}</code> 个群 / 频道
· 生效规则：<code>{valid_rules}</code> 条
· 自动收纳规则：<code>{len(self.db.list_routes())}</code> 条

<b>🎯 历史统计</b>
· 总计命中：<code>{html.escape(stats.get('total_hits', '0'))}</code>
· 最近命中分组：<code>{html.escape(last_folder)}</code>
· 最近命中时间：<code>{html.escape(last_time)}</code>

<b>📂 已启用分组概览</b>
<blockquote>{active_block}</blockquote>"""

    def render_sync_message(self, sync_report: SyncReport, route_report: RouteReport) -> str:
        lines = [
            "✅ <b>TG-Radar 同步执行完成</b>",
            "",
            "<b>📂 分组同步结果</b>",
            f"· 变动状态：<code>{'发现变动并已更新' if sync_report.has_changes else '数据无变动'}</code>",
            f"· 耗时：<code>{sync_report.elapsed_seconds:.1f} 秒</code>",
            f"· 新分组：<code>{len(sync_report.discovered)}</code> · 改名：<code>{len(sync_report.renamed)}</code> · 删除：<code>{len(sync_report.deleted)}</code>",
        ]
        if sync_report.discovered:
            lines.extend([f"· ✨ 新分组：<code>{html.escape(name)}</code>" for name in sync_report.discovered])
        if sync_report.renamed:
            lines.extend([f"· 🔄 改名：<code>{html.escape(old)}</code> → <code>{html.escape(new)}</code>" for old, new in sync_report.renamed])
        if sync_report.deleted:
            lines.extend([f"· 🗑️ 删除：<code>{html.escape(name)}</code>" for name in sync_report.deleted])

        lines += ["", "<b>🔀 自动收纳扫描</b>"]
        if route_report.created or route_report.queued or route_report.matched_zero or route_report.already_in or route_report.errors:
            for fn in route_report.created:
                lines.append(f"· ✨ 自动新建了分组：<code>{html.escape(fn)}</code>")
            for fn, cnt in route_report.queued.items():
                lines.append(f"· ⏳ 已排队补群：<code>{html.escape(fn)}</code> · <code>{cnt}</code>")
            for fn, cnt in route_report.already_in.items():
                lines.append(f"· 📦 已存在于分组：<code>{html.escape(fn)}</code> · <code>{cnt}</code>")
            for fn in route_report.matched_zero:
                lines.append(f"· 🔕 未匹配到任何群：<code>{html.escape(fn)}</code>")
            for fn, err in route_report.errors.items():
                lines.append(f"· ❌ <code>{html.escape(fn)}</code> · {html.escape(err)}")
        else:
            lines.append("· <i>没有新的自动收纳动作</i>")

        lines += ["", f"💡 <i>如果发现了新分组，记得发送 <code>{html.escape(self.config.cmd_prefix)}enable [分组名]</code> 开启监控。</i>"]
        return "\n".join(lines)

    def find_folder(self, query: str) -> str | None:
        rows = self.db.list_folders()
        names = [row["folder_name"] for row in rows]
        if query in names:
            return query
        lower = query.lower()
        for name in names:
            if name.lower() == lower:
                return name
        candidates = [name for name in names if lower in name.lower()]
        return candidates[0] if len(candidates) == 1 else None

    def parse_int_or_none(self, raw: str) -> int | None:
        raw = raw.strip()
        if raw.lower() in {"", "off", "none", "null", "me"}:
            return None
        return int(raw)

    def restart_services(self, delay: float = 0.0) -> None:
        cmd = [
            "bash",
            "-lc",
            f"sleep {delay}; systemctl restart {self.config.service_name_prefix}-core {self.config.service_name_prefix}-admin",
        ]
        subprocess.Popen(cmd)

    def write_last_message(self, msg_id: int, action: str) -> None:
        path = self.config.work_dir / ".last_msg"
        path.write_text(json.dumps({"chat_id": "me", "msg_id": msg_id, "action": action}, ensure_ascii=False), encoding="utf-8")


async def run(work_dir: Path) -> None:
    app = AdminApp(work_dir)
    await app.run()
