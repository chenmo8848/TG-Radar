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
from .telegram_utils import (
    blockquote_preview,
    bullet,
    dialog_filter_title,
    escape,
    format_duration,
    html_code,
    normalize_pattern_from_terms,
    panel,
    section,
    shorten_path,
    try_remove_terms_from_pattern,
)
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
                    panel(
                        "TG-Radar 命令执行异常",
                        [section("异常说明", [blockquote_preview(str(exc), 500)])],
                        "<i>详细堆栈已写入 admin.log，可在终端执行 <code>TR logs admin</code> 排查。</i>",
                    ),
                )

    async def dispatch(self, event: events.NewMessage.Event, command: str, args: str) -> None:
        prefix = escape(self.config.cmd_prefix)

        if command == "help":
            await self.safe_reply(event, self.render_help_message(), auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command == "ping":
            stats = self.db.get_runtime_stats()
            await self.safe_reply(
                event,
                panel(
                    "TG-Radar 在线心跳",
                    [section("快速状态", [bullet("管理层运行", format_duration((datetime.now() - self.started_at).total_seconds())), bullet("历史命中", stats.get("total_hits", "0")), bullet("热更新轮询", f"{self.config.revision_poll_seconds} 秒"), bullet("自动同步", f"{self.config.sync_interval_seconds} 秒")])],
                ),
                auto_delete=12,
            )
            return

        if command == "status":
            await self.safe_reply(event, self.render_status_message())
            return

        if command == "version":
            await self.safe_reply(
                event,
                panel(
                    "TG-Radar 版本信息",
                    [
                        section("当前构建", [bullet("版本", __version__), bullet("架构", "Plan C / Admin + Core / SQLite WAL"), bullet("终端命令", "TR")]),
                        section("部署位置", [bullet("工作目录", shorten_path(self.config.work_dir), code=False), bullet("会话策略", "编辑原消息 + 面板自动回收", code=False)]),
                    ],
                ),
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
            await self.safe_reply(event, panel("系统通知目标已更新", [section("新配置", [bullet("通知去向", value if value is not None else "Saved Messages"), bullet("覆盖范围", "启动 / 同步 / 更新 / 恢复", code=False)])]))
            return

        if command == "setalert":
            value = self.parse_int_or_none(args)
            update_config_data(self.config.work_dir, {"global_alert_channel_id": value})
            self.config = load_config(self.config.work_dir)
            self.db.log_event("INFO", "SET_ALERT", str(value))
            await self.safe_reply(event, panel("默认告警频道已更新", [section("新配置", [bullet("默认告警", value if value is not None else "未设置"), bullet("生效范围", "未单独配置告警频道的分组", code=False)])]))
            return

        if command == "setprefix":
            value = args.strip()
            if not value or len(value) > 3 or " " in value or any(ch in value for ch in ["\\", '"', "'"]):
                await self.safe_reply(event, panel("命令前缀格式无效", [section("输入要求", [bullet("长度", "1-3 个字符", code=False), bullet("限制", "不能包含空格、引号、反斜杠", code=False)])]))
                return
            update_config_data(self.config.work_dir, {"cmd_prefix": value})
            self.db.log_event("INFO", "SET_PREFIX", value)
            self.write_last_message(event.id, "restart")
            await self.safe_reply(event, panel("命令前缀已更新", [section("新前缀", [bullet("命令前缀", value), bullet("试用命令", f"{value}help")])], "<i>接下来会自动重启 Admin / Core，新的前缀会在服务恢复后立刻生效。</i>"), auto_delete=0)
            self.restart_services(delay=1.2)
            return

        if command == "log":
            limit = 30
            if args.isdigit():
                limit = min(200, max(1, int(args)))
            rows = self.db.recent_logs(limit)
            if not rows:
                await self.safe_reply(event, panel("最近运行日志", [section("结果", ["· <i>目前还没有可展示的日志。</i>"])]))
                return
            body = "\n".join(f"[{row['created_at']}] {row['level']}/{row['action']} :: {row['detail']}" for row in rows)
            await self.safe_reply(event, panel("最近运行日志", [section("日志内容", [blockquote_preview(body, 1800)])]), auto_delete=max(90, self.config.panel_auto_delete_seconds))
            return

        if command == "folders":
            rows = self.db.list_folders()
            if not rows:
                await self.safe_reply(event, panel("TG 分组总览", [section("当前状态", ["· <i>系统里还没有任何分组记录。先执行一次同步，或先在 Telegram 侧创建分组。</i>"])]))
                return
            blocks = []
            for row in rows:
                folder_name = row["folder_name"]
                group_count = self.db.count_cache_for_folder(folder_name)
                rule_count = self.db.count_rules_for_folder(folder_name)
                icon = "🟢" if int(row["enabled"]) == 1 else "⚪"
                blocks.append(f"{icon} <b>{escape(folder_name)}</b>\n· 监听：{html_code('开启' if int(row['enabled']) == 1 else '关闭')}\n· 群数：{html_code(group_count)}\n· 规则：{html_code(rule_count)}")
            await self.safe_reply(event, panel("TG 分组总览", [section("当前分组", blocks)]), auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command == "rules":
            if not args:
                await self.safe_reply(event, panel("缺少参数", [section("示例", [f"<code>{prefix}rules 业务群</code>"])]))
                return
            folder = self.find_folder(args)
            if folder is None:
                await self.safe_reply(event, panel("找不到该分组", [section("提示", [f"· 先发送 <code>{prefix}folders</code> 查看系统已识别的分组。"])]))
                return
            rows = self.db.get_rules_for_folder(folder)
            if not rows:
                await self.safe_reply(event, panel(f"{folder} 的规则面板", [section("当前状态", ["· <i>该分组还没有任何启用中的规则。</i>"])]))
                return
            blocks = []
            for row in rows:
                blocks.append(f"<b>{escape(row['rule_name'])}</b>\n· 表达式：<code>{escape(row['pattern'])}</code>\n· 更新时间：<code>{escape(row['updated_at'])}</code>")
            await self.safe_reply(event, panel(f"{folder} 的规则面板", [section("已启用规则", blocks)]), auto_delete=max(80, self.config.panel_auto_delete_seconds))
            return

        if command == "enable":
            if not args:
                await self.safe_reply(event, panel("缺少参数", [section("示例", [f"<code>{prefix}enable 业务群</code>"])]))
                return
            folder = self.find_folder(args)
            if folder is None:
                await self.safe_reply(event, panel("找不到该分组", [section("提示", [f"· 先发送 <code>{prefix}folders</code> 查看列表。"])]))
                return
            self.db.set_folder_enabled(folder, True)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "ENABLE_FOLDER", folder)
            await self.safe_reply(event, panel("分组监控已开启", [section("当前动作", [bullet("分组", folder), bullet("状态", "开启")])], "<i>这项变更已经写入 revision，Core 会在轮询周期内自动热更新。</i>"))
            return

        if command == "disable":
            if not args:
                await self.safe_reply(event, panel("缺少参数", [section("示例", [f"<code>{prefix}disable 业务群</code>"])]))
                return
            folder = self.find_folder(args)
            if folder is None:
                await self.safe_reply(event, panel("找不到该分组", [section("提示", [f"· 先发送 <code>{prefix}folders</code> 查看列表。"])]))
                return
            self.db.set_folder_enabled(folder, False)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "DISABLE_FOLDER", folder)
            await self.safe_reply(event, panel("分组监控已关闭", [section("当前动作", [bullet("分组", folder), bullet("状态", "关闭")])], "<i>对应监听目标会在 revision watcher 重新装载后停止匹配。</i>"))
            return

        if command == "addrule":
            tokens = shlex.split(args)
            if len(tokens) < 3:
                await self.safe_reply(event, panel("参数不足", [section("示例", [f"<code>{prefix}addrule 业务群 核心词 苹果 华为</code>"])]))
                return
            folder = self.find_folder(tokens[0]) or tokens[0]
            rule_name = tokens[1]
            pattern = normalize_pattern_from_terms(" ".join(tokens[2:]))
            if self.db.get_folder(folder) is None:
                self.db.upsert_folder(folder, None, enabled=False)
            self.db.upsert_rule(folder, rule_name, pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "ADD_RULE", f"{folder}/{rule_name} -> {pattern}")
            await self.safe_reply(event, panel("规则已保存", [section("规则详情", [bullet("分组", folder), bullet("规则名", rule_name), bullet("表达式", pattern)])], "<i>如需让该分组立即参与监听，请确认分组处于开启状态。</i>"))
            return

        if command == "delrule":
            tokens = shlex.split(args)
            if len(tokens) < 2:
                await self.safe_reply(event, panel("参数不足", [section("示例", [f"<code>{prefix}delrule 业务群 核心词</code>", f"<code>{prefix}delrule 业务群 核心词 苹果</code>"])]))
                return
            folder = self.find_folder(tokens[0]) or tokens[0]
            rule_name = tokens[1]
            terms = tokens[2:]
            rows = self.db.get_rules_for_folder(folder)
            rule = next((row for row in rows if row["rule_name"] == rule_name), None)
            if rule is None:
                await self.safe_reply(event, panel("找不到该规则", [section("定位信息", [bullet("分组", folder), bullet("规则名", rule_name)])]))
                return
            if not terms:
                self.db.delete_rule(folder, rule_name)
                sync_snapshot_to_config(self.config.work_dir, self.db)
                self.db.log_event("INFO", "DELETE_RULE", f"{folder}/{rule_name}")
                await self.safe_reply(event, panel("规则已删除", [section("删除结果", [bullet("分组", folder), bullet("规则名", rule_name)])]))
                return
            new_pattern = try_remove_terms_from_pattern(rule["pattern"], terms)
            if not new_pattern:
                self.db.delete_rule(folder, rule_name)
                sync_snapshot_to_config(self.config.work_dir, self.db)
                await self.safe_reply(event, panel("规则已清空", [section("删除结果", [bullet("分组", folder), bullet("规则名", rule_name)])]))
                return
            self.db.update_rule_pattern(folder, rule_name, new_pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "UPDATE_RULE", f"{folder}/{rule_name} -> {new_pattern}")
            await self.safe_reply(event, panel("规则已更新", [section("新表达式", [f"<code>{escape(new_pattern)}</code>"])]))
            return

        if command == "routes":
            rows = self.db.list_routes()
            if not rows:
                await self.safe_reply(event, panel("自动收纳规则面板", [section("当前状态", ["· <i>当前没有自动收纳规则。</i>"])]))
                return
            blocks = []
            for row in rows:
                blocks.append(f"<b>{escape(row['folder_name'])}</b>\n· 路由表达式：<code>{escape(row['pattern'])}</code>\n· 更新时间：<code>{escape(row['updated_at'])}</code>")
            await self.safe_reply(event, panel("自动收纳规则面板", [section("当前规则", blocks)]), auto_delete=max(75, self.config.panel_auto_delete_seconds))
            return

        if command == "addroute":
            tokens = shlex.split(args)
            if len(tokens) < 2:
                await self.safe_reply(event, panel("参数不足", [section("示例", [f"<code>{prefix}addroute 业务群 供需 担保</code>"])]))
                return
            folder = self.find_folder(tokens[0]) or tokens[0]
            if self.db.get_folder(folder) is None:
                self.db.upsert_folder(folder, None, enabled=False)
                self.db.upsert_rule(folder, f"{folder}监控", "(示范词A|示范词B)")
            pattern = normalize_pattern_from_terms(" ".join(tokens[1:]))
            self.db.set_route(folder, pattern)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "ADD_ROUTE", f"{folder} -> {pattern}")
            await self.safe_reply(event, panel("自动收纳规则已保存", [section("规则详情", [bullet("分组", folder), bullet("路由表达式", pattern)])], "<i>后续自动同步会持续扫描新群，并把命中的目标加入路由补群队列。</i>"))
            return

        if command == "delroute":
            if not args:
                await self.safe_reply(event, panel("参数不足", [section("示例", [f"<code>{prefix}delroute 业务群</code>"])]))
                return
            folder = self.find_folder(args) or args.strip()
            if not self.db.delete_route(folder):
                await self.safe_reply(event, panel("没有找到该自动收纳规则", [section("定位信息", [bullet("分组", folder)])]))
                return
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "DELETE_ROUTE", folder)
            await self.safe_reply(event, panel("自动收纳规则已删除", [section("删除结果", [bullet("分组", folder)])]))
            return

        if command == "sync":
            await self.run_sync_command(event)
            return

        if command == "restart":
            self.write_last_message(event.id, "restart")
            await self.safe_reply(event, panel("TG-Radar 即将重启", [section("执行说明", [bullet("影响范围", "Admin / Core 双服务", code=False), bullet("任务状态", "数据库中未完成的路由任务会继续保留", code=False), bullet("恢复方式", "重启后系统会自动接管未完成任务", code=False)])]), auto_delete=0)
            self.db.log_event("INFO", "RESTART", "restart requested from Telegram")
            self.restart_services(delay=1.2)
            return

        if command == "update":
            self.write_last_message(event.id, "update")
            await self.run_update_command(event)
            return

        await self.safe_reply(event, panel("未知命令", [section("下一步", [f"· 发送 <code>{prefix}help</code> 查看可用命令。"])]))

    async def run_sync_command(self, event: events.NewMessage.Event) -> None:
        if self.sync_lock.locked():
            await self.safe_reply(event, panel("系统正忙", [section("提示", ["· 后台正在执行其他同步任务，请稍后再试。"])]))
            return
        async with self.sync_lock:
            await self.safe_reply(event, panel("正在执行全量同步", [section("同步阶段", ["· 比对 Telegram 分组拓扑", "· 回写缓存与规则快照", "· 扫描自动收纳并补充队列", "· revision 变更后立即热更新"])]), auto_delete=0)
            sync_report = await sync_dialog_folders(self.client, self.db)
            route_report = await scan_auto_routes(self.client, self.db)
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self.db.log_event("INFO", "SYNC", f"sync changed={sync_report.has_changes} queued={sum(route_report.queued.values())}")
            await self.safe_reply(event, self.render_sync_message(sync_report, route_report), auto_delete=max(55, self.config.panel_auto_delete_seconds))

    async def run_update_command(self, event: events.NewMessage.Event) -> None:
        if not (self.config.work_dir / ".git").exists():
            await self.safe_reply(event, panel("当前目录不是 git 仓库", [section("提示", ["· 请用 git 方式部署后再执行 update。"])]))
            return
        await self.safe_reply(event, panel("正在拉取最新代码", [section("执行动作", ["· 运行 git pull --ff-only", "· 成功后自动重启双服务"])]), auto_delete=0)
        proc = await asyncio.create_subprocess_exec("git", "-C", str(self.config.work_dir), "pull", "--ff-only", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        stdout, _ = await proc.communicate()
        output = (stdout or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            self.db.log_event("ERROR", "UPDATE", output or f"git pull failed: {proc.returncode}")
            await self.safe_reply(event, panel("代码更新失败", [section("输出内容", [blockquote_preview(output or 'git pull failed', 1400)])]))
            return
        self.db.log_event("INFO", "UPDATE", output or "git pull ok")
        await self.safe_reply(event, panel("代码更新完成", [section("git 输出", [blockquote_preview(output or 'Already up to date.', 1400)])], "<i>接下来会自动重启 Admin / Core，加载最新代码。</i>"), auto_delete=0)
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
            new_filter = types.DialogFilter(id=folder_id, title=task.folder_name, pinned_peers=[], include_peers=peers[:100], exclude_peers=[], contacts=False, non_contacts=False, groups=False, broadcasts=False, bots=False, exclude_muted=False, exclude_read=False, exclude_archived=False)
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
        title = "TG-Radar 自动同步报告" if automatic else "TG-Radar 手动同步报告"
        status = "发现变动并已更新" if sync_report.has_changes or route_report.queued or route_report.created else "同步完成，数据无变动"

        folder_rows: list[str] = []
        if sync_report.discovered:
            folder_rows.extend(f"· 新分组：<code>{escape(name)}</code>" for name in sync_report.discovered)
        if sync_report.renamed:
            folder_rows.extend(f"· 改名：<code>{escape(old)}</code> → <code>{escape(new)}</code>" for old, new in sync_report.renamed)
        if sync_report.deleted:
            folder_rows.extend(f"· 删除：<code>{escape(name)}</code>" for name in sync_report.deleted)
        if not folder_rows:
            folder_rows.append("· <i>本次没有新增、改名或删除任何分组。</i>")

        route_rows: list[str] = []
        for name in route_report.created:
            route_rows.append(f"· 新建分组：<code>{escape(name)}</code>")
        for name, cnt in route_report.queued.items():
            route_rows.append(f"· 排队补群：<code>{escape(name)}</code> · <code>{cnt}</code>")
        for name, cnt in route_report.already_in.items():
            route_rows.append(f"· 已在分组：<code>{escape(name)}</code> · <code>{cnt}</code>")
        for name in route_report.matched_zero:
            route_rows.append(f"· 没有命中：<code>{escape(name)}</code>")
        for name, err in route_report.errors.items():
            route_rows.append(f"· 错误：<code>{escape(name)}</code> · {escape(err)}")
        if not route_rows:
            route_rows.append("· <i>本次没有新增自动收纳动作。</i>")

        active_rows = [f"· <b>{escape(name)}</b> · <code>{cnt}</code> 个群" for name, cnt in sync_report.active.items()]
        if not active_rows:
            active_rows = ["· <i>当前没有读取到任何分组群数据。</i>"]

        message = panel(title, [section("执行摘要", [bullet("结果", status), bullet("耗时", f"{sync_report.elapsed_seconds:.1f} 秒"), bullet("时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))]), section("分组变动", folder_rows), section("自动收纳", route_rows), section("当前规模", active_rows[:8])], f"<i>发现新分组后，发送 <code>{escape(self.config.cmd_prefix)}enable 分组名</code> 即可开启监听。</i>")
        try:
            msg = await self.client.send_message(target, message, link_preview=False)
            if msg and self.config.notify_auto_delete_seconds > 0:
                asyncio.create_task(self.delete_later(msg, self.config.notify_auto_delete_seconds))
        except Exception as exc:
            self.logger.warning("send sync report failed: %s", exc)

    async def send_startup_notification(self) -> None:
        assert self.client is not None
        rows = self.db.list_folders()
        enabled = [row for row in rows if int(row["enabled"]) == 1]
        folder_rows = []
        for row in enabled[:8]:
            folder_name = row["folder_name"]
            folder_rows.append(f"· <b>{escape(folder_name)}</b> · 群 <code>{self.db.count_cache_for_folder(folder_name)}</code> · 规则 <code>{self.db.count_rules_for_folder(folder_name)}</code>")
        if not folder_rows:
            folder_rows = ["· <i>当前没有开启任何分组监听。</i>"]

        route_rows = [f"· <code>{escape(row['pattern'])}</code> → <code>{escape(row['folder_name'])}</code>" for row in self.db.list_routes()[:8]] or ["· <i>当前没有自动收纳规则。</i>"]
        target_map, valid_rules = self.db.build_target_map(self.config.global_alert_channel_id)
        startup_card = panel("TG-Radar 已上线", [section("运行概况", [bullet("架构", "Plan C / Admin + Core / SQLite WAL"), bullet("版本", __version__), bullet("启动时间", self.started_at.strftime("%Y-%m-%d %H:%M:%S")), bullet("自动同步", f"每 {self.config.sync_interval_seconds} 秒"), bullet("热更新", f"每 {self.config.revision_poll_seconds} 秒")]), section("当前规模", [bullet("活跃分组", f"{len(enabled)} / {len(rows)}"), bullet("监听目标", f"{len(target_map)} 个群 / 频道"), bullet("生效规则", f"{valid_rules} 条")]), section("已启用分组", folder_rows), section("自动收纳规则", route_rows)], f"<i>在收藏夹发送 <code>{escape(self.config.cmd_prefix)}help</code> 可以打开完整管理面板。</i>")

        last_msg_path = self.config.work_dir / ".last_msg"
        target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "me"
        msg_obj = None
        if last_msg_path.exists():
            try:
                ctx = json.loads(last_msg_path.read_text(encoding="utf-8"))
                action = ctx.get("action", "restart")
                prefix_text = "✨ <b>代码更新完成</b>\n\n" if action == "update" else "🔄 <b>服务重启完成</b>\n\n"
                msg_obj = await self.client.edit_message("me", int(ctx["msg_id"]), prefix_text + startup_card)
                last_msg_path.unlink(missing_ok=True)
                self.db.log_event("INFO", "RESTORE", f"system back online after {action}")
            except Exception:
                pass

        if msg_obj is None:
            try:
                msg_obj = await self.client.send_message(target, startup_card, link_preview=False)
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

    async def safe_reply(self, event: events.NewMessage.Event, text: str, auto_delete: int | None = None, prefer_edit: bool = True, recycle_source_on_reply: bool = True) -> None:
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
        prefix = escape(self.config.cmd_prefix)
        return panel("TG-Radar 管理面板", [section("运行状态", [f"<code>{prefix}status</code> · 详细状态面板", f"<code>{prefix}ping</code> · 快速心跳检测", f"<code>{prefix}log 30</code> · 最近运行日志", f"<code>{prefix}version</code> · 版本与部署信息", f"<code>{prefix}config</code> · 关键配置总览"]), section("分组与规则", [f"<code>{prefix}folders</code> · 查看全部 TG 分组", f"<code>{prefix}rules 分组名</code> · 查看分组规则", f"<code>{prefix}enable 分组名</code> · 开启监控", f"<code>{prefix}disable 分组名</code> · 关闭监控", f"<code>{prefix}addrule 分组 规则名 关键词...</code>", f"<code>{prefix}delrule 分组 规则名 [关键词...]</code>"]), section("自动收纳", [f"<code>{prefix}routes</code> · 查看路由规则", f"<code>{prefix}addroute 分组 匹配词...</code>", f"<code>{prefix}delroute 分组</code>"]), section("系统维护", [f"<code>{prefix}sync</code> · 强制执行一次同步", f"<code>{prefix}setnotify ID/off</code> · 设置通知频道", f"<code>{prefix}setalert ID/off</code> · 设置默认告警", f"<code>{prefix}setprefix 新前缀</code> · 修改前缀", f"<code>{prefix}update</code> · 更新并重启", f"<code>{prefix}restart</code> · 直接重启双服务"])], "<i>面板会优先编辑原命令消息，并在设定时间后自动回收，尽量减少 Saved Messages 的刷屏感。</i>")

    def render_config_message(self) -> str:
        notify_target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "Saved Messages"
        alert_target = self.config.global_alert_channel_id if self.config.global_alert_channel_id is not None else "未设置"
        return panel("TG-Radar 关键配置", [section("通信与路由", [bullet("API_ID", self.config.api_id), bullet("默认告警", alert_target), bullet("系统通知", notify_target), bullet("命令前缀", self.config.cmd_prefix)]), section("运行与回收", [bullet("自动同步", f"{self.config.sync_interval_seconds} 秒"), bullet("热更新轮询", f"{self.config.revision_poll_seconds} 秒"), bullet("路由节流", f"{self.config.route_worker_interval_seconds} 秒"), bullet("面板回收", f"{self.config.panel_auto_delete_seconds} 秒"), bullet("通知回收", f"{self.config.notify_auto_delete_seconds} 秒")]), section("部署信息", [bullet("服务前缀", self.config.service_name_prefix), bullet("终端命令", "TR"), bullet("工作目录", shorten_path(self.config.work_dir), code=False), bullet("仓库地址", self.config.repo_url or "未设置", code=False)])])

    def render_status_message(self) -> str:
        stats = self.db.get_runtime_stats()
        last_folder = stats.get("last_hit_folder") or "暂无记录"
        last_time = stats.get("last_hit_time") or "暂无记录"
        rows = self.db.list_folders()
        enabled_cnt = sum(1 for row in rows if int(row["enabled"]) == 1)
        target_map, valid_rules = self.db.build_target_map(self.config.global_alert_channel_id)
        queue_size = self.db.pending_route_count()
        active_rows = []
        for row in rows:
            if int(row["enabled"]) != 1:
                continue
            folder_name = row["folder_name"]
            active_rows.append(f"· {escape(folder_name)} · 群 <code>{self.db.count_cache_for_folder(folder_name)}</code> · 规则 <code>{self.db.count_rules_for_folder(folder_name)}</code>")
            if len(active_rows) >= 8:
                break
        if not active_rows:
            active_rows = ["· <i>暂无启用分组。</i>"]
        q_info = f"{queue_size} 个任务待处理" if queue_size > 0 else "空闲"
        return panel("TG-Radar 详细状态", [section("运行状态", [bullet("系统状态", "稳定运行中", code=False), bullet("持续运行", format_duration((datetime.now() - self.started_at).total_seconds())), bullet("自动同步", f"{self.config.sync_interval_seconds} 秒"), bullet("热更新轮询", f"{self.config.revision_poll_seconds} 秒"), bullet("路由队列", q_info, code=False)]), section("监控规模", [bullet("活跃分组", f"{enabled_cnt} / {len(rows)}"), bullet("监听目标", f"{len(target_map)} 个群 / 频道"), bullet("生效规则", f"{valid_rules} 条"), bullet("自动收纳规则", f"{len(self.db.list_routes())} 条")]), section("历史统计", [bullet("总计命中", stats.get("total_hits", "0")), bullet("最近命中分组", last_folder), bullet("最近命中时间", last_time)]), section("已启用分组", active_rows)])

    def render_sync_message(self, sync_report: SyncReport, route_report: RouteReport) -> str:
        folder_rows: list[str] = []
        if sync_report.discovered:
            folder_rows.extend(f"· 新分组：<code>{escape(name)}</code>" for name in sync_report.discovered)
        if sync_report.renamed:
            folder_rows.extend(f"· 改名：<code>{escape(old)}</code> → <code>{escape(new)}</code>" for old, new in sync_report.renamed)
        if sync_report.deleted:
            folder_rows.extend(f"· 删除：<code>{escape(name)}</code>" for name in sync_report.deleted)
        if not folder_rows:
            folder_rows = ["· <i>分组拓扑没有变化。</i>"]

        route_rows: list[str] = []
        for fn in route_report.created:
            route_rows.append(f"· 新建分组：<code>{escape(fn)}</code>")
        for fn, cnt in route_report.queued.items():
            route_rows.append(f"· 排队补群：<code>{escape(fn)}</code> · <code>{cnt}</code>")
        for fn, cnt in route_report.already_in.items():
            route_rows.append(f"· 已在分组：<code>{escape(fn)}</code> · <code>{cnt}</code>")
        for fn in route_report.matched_zero:
            route_rows.append(f"· 没有命中：<code>{escape(fn)}</code>")
        for fn, err in route_report.errors.items():
            route_rows.append(f"· 错误：<code>{escape(fn)}</code> · {escape(err)}")
        if not route_rows:
            route_rows = ["· <i>没有新的自动收纳动作。</i>"]

        return panel("TG-Radar 同步完成", [section("同步结果", [bullet("变动状态", "发现变动并已更新" if sync_report.has_changes else "数据无变动", code=False), bullet("耗时", f"{sync_report.elapsed_seconds:.1f} 秒"), bullet("新分组", len(sync_report.discovered)), bullet("改名", len(sync_report.renamed)), bullet("删除", len(sync_report.deleted))]), section("分组变动", folder_rows), section("自动收纳", route_rows)], f"<i>如果发现了新分组，记得发送 <code>{escape(self.config.cmd_prefix)}enable 分组名</code> 开启监控。</i>")

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
        cmd = ["bash", "-lc", f"sleep {delay}; systemctl restart {self.config.service_name_prefix}-core {self.config.service_name_prefix}-admin"]
        subprocess.Popen(cmd)

    def write_last_message(self, msg_id: int, action: str) -> None:
        path = self.config.work_dir / ".last_msg"
        path.write_text(json.dumps({"chat_id": "me", "msg_id": msg_id, "action": action}, ensure_ascii=False), encoding="utf-8")


async def run(work_dir: Path) -> None:
    app = AdminApp(work_dir)
    await app.run()
