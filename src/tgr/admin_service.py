from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events, functions, types, utils

from .app.commands import CommandContext, CommandRegistry
from .command_bus import CommandBus
from .compat import seed_db_from_legacy_config_if_needed
from .config import load_config, sync_snapshot_to_config
from .db import AdminJob, RadarDB, RouteTask
from .executors import JobResult
from .logger import setup_logger
from .plugin_manager import PluginManager
from .scheduler import AdminScheduler
from .services.message_io import MessageIO
from .services.panels import render_job_accept_panel
from .sync_logic import RouteReport, SyncReport, sync_dialog_folders
from .telegram_utils import blockquote_preview, bullet, dialog_filter_title, escape, format_duration, panel, section, shorten_path
from .version import __version__


class AdminApp:
    def __init__(self, work_dir: Path) -> None:
        self.config = load_config(work_dir)
        self.logger = setup_logger("tg-radar-admin", self.config.logs_dir / "admin.log")
        self.db = RadarDB(self.config.db_path)
        seed_db_from_legacy_config_if_needed(work_dir, self.db)
        self.started_at = datetime.now()
        self.started_monotonic = time.monotonic()
        self.stop_event = asyncio.Event()
        self.command_client: TelegramClient | None = None
        self.worker_client: TelegramClient | None = None
        self.client: TelegramClient | None = None
        self.self_id: int | None = None
        self.message_io: MessageIO | None = None
        self.command_bus = CommandBus(self.db, notifier=self._notify_scheduler)
        self.scheduler: AdminScheduler | None = None
        self.last_sync_result: tuple[SyncReport, RouteReport] | None = None
        self.last_command_ts = 0.0
        self._last_snapshot_queued_at = 0.0
        self._startup_sync_note = ""
        self.registry = CommandRegistry()
        self.plugin_manager = PluginManager(work_dir, self.config, logger=self.logger)

    async def reload_admin_plugins(self) -> None:
        self.config = load_config(self.config.work_dir)
        self.plugin_manager = PluginManager(self.config.work_dir, self.config, logger=self.logger)
        self.registry = CommandRegistry()
        self.plugin_manager.load_admin_plugins(self.registry)
        await self.plugin_manager.refresh_admin_health(self)

    def _notify_scheduler(self) -> None:
        if self.scheduler is not None:
            self.scheduler.notify_new_job()

    def try_log_event(self, level: str, action: str, detail: str) -> None:
        try:
            self.db.log_event(level, action, detail)
        except Exception:
            pass

    def parse_tokens(self, args: str) -> list[str]:
        try:
            import shlex

            return shlex.split(args) if args else []
        except Exception:
            return [part for part in args.strip().split() if part]

    def find_folder(self, raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        rows = self.db.list_folders()
        exact = next((str(row["folder_name"]) for row in rows if str(row["folder_name"]) == raw), None)
        if exact is not None:
            return exact
        matches = [str(row["folder_name"]) for row in rows if str(row["folder_name"]).lower().startswith(raw.lower())]
        return matches[0] if len(matches) == 1 else None

    async def require_folder(self, ctx: CommandContext, *, allow_unknown: bool = False) -> str | None:
        if not ctx.tokens:
            await self.reply_panel(
                ctx.event,
                panel("缺少参数", [section("提示", [f"· 先发送 <code>{escape(self.config.cmd_prefix)}folders</code> 查看分组列表。"])]),
                auto_delete=0,
            )
            return None
        folder = self.find_folder(ctx.tokens[0])
        if folder is None and allow_unknown:
            return ctx.tokens[0]
        if folder is None:
            await self.reply_panel(
                ctx.event,
                panel("找不到该分组", [section("提示", [f"· 先发送 <code>{escape(self.config.cmd_prefix)}folders</code> 查看已同步的分组。"])]),
                auto_delete=0,
            )
        return folder

    def parse_int_or_none(self, raw: str) -> int | None:
        text = (raw or "").strip()
        if not text or text.lower() in {"off", "none", "null"}:
            return None
        return int(text)

    async def reply_panel(self, event, text: str, *, auto_delete: int = 0) -> None:
        assert self.message_io is not None
        await self.message_io.reply(event, text, auto_delete=auto_delete)

    async def submit_heavy_job(
        self,
        ctx: CommandContext,
        kind: str,
        *,
        priority: int,
        dedupe_key: str | None,
        delay_seconds: float,
        detail: str,
    ) -> None:
        payload = {"reply_to": int(ctx.event.id), "trace": ctx.trace, "source_command": ctx.command}
        result = self.command_bus.submit(
            kind,
            payload=payload,
            priority=priority,
            dedupe_key=dedupe_key,
            origin="telegram",
            visible=True,
            delay_seconds=delay_seconds,
        )
        self.try_log_event("INFO", "JOB_QUEUE", f"{ctx.trace} {kind} queued")
        await self.reply_panel(ctx.event, render_job_accept_panel(ctx.command, ctx.trace, result.job_id, detail), auto_delete=0)

    def collect_folder_stats(self) -> dict[str, object]:
        rows = self.db.list_folders()
        enabled_rows = [row for row in rows if int(row["enabled"]) == 1]
        folder_cards = []
        total_cached = 0
        enabled_cached = 0
        total_rules = 0
        enabled_rules = 0
        for row in rows:
            folder_name = str(row["folder_name"])
            cache_count = self.db.count_cache_for_folder(folder_name)
            rule_count = self.db.count_rules_for_folder(folder_name)
            total_cached += cache_count
            total_rules += rule_count
            if int(row["enabled"]) == 1:
                enabled_cached += cache_count
                enabled_rules += rule_count
            folder_cards.append(
                {
                    "folder_name": folder_name,
                    "folder_id": row["folder_id"],
                    "enabled": int(row["enabled"]) == 1,
                    "cache_count": cache_count,
                    "rule_count": rule_count,
                    "alert_channel_id": row["alert_channel_id"],
                }
            )
        target_map, valid_rules = self.db.build_target_map(self.config.global_alert_channel_id)
        return {
            "rows": rows,
            "folder_cards": folder_cards,
            "enabled_rows": enabled_rows,
            "total_folders": len(rows),
            "enabled_folders": len(enabled_rows),
            "total_cached": total_cached,
            "enabled_cached": enabled_cached,
            "total_rules": total_rules,
            "enabled_rules": enabled_rules,
            "route_count": len(self.db.list_routes()),
            "target_count": len(target_map),
            "valid_rules": valid_rules,
            "queue_size": self.db.pending_route_count(),
        }

    def render_ping_message(self) -> str:
        return panel(
            "TG-Radar 前台热路径在线",
            [
                section(
                    "快速状态",
                    [
                        bullet("版本", __version__, code=False),
                        bullet("运行时长", format_duration(time.monotonic() - self.started_monotonic), code=False),
                        bullet("命令前缀", self.config.cmd_prefix, code=False),
                        bullet("交互模式", "轻命令直接回复 / 重任务后台回包", code=False),
                    ],
                )
            ],
            "<i>这个命令不进入重任务队列；如果它也慢，优先检查 Telegram 会话、网络和 VPS 负载。</i>",
        )

    def render_config_message(self) -> str:
        notify_target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "Saved Messages"
        alert_target = self.config.global_alert_channel_id if self.config.global_alert_channel_id is not None else "未设置"
        return panel(
            "TG-Radar 关键配置",
            [
                section(
                    "通信与路由",
                    [
                        bullet("API_ID", self.config.api_id),
                        bullet("默认告警", alert_target, code=False),
                        bullet("系统通知", notify_target, code=False),
                        bullet("命令前缀", self.config.cmd_prefix, code=False),
                    ],
                ),
                section(
                    "运行策略",
                    [
                        bullet("运行模式", self.config.operation_mode, code=False),
                        bullet("自动同步", f"每日 {self.config.auto_sync_time}" if self.config.auto_sync_enabled else "已关闭", code=False),
                        bullet("自动归纳", f"每日 {self.config.auto_route_time}" if self.config.auto_route_enabled else "已关闭", code=False),
                        bullet("轻命令", "直接回复，不走后台任务", code=False),
                        bullet("重任务", "排队执行并单独回包", code=False),
                    ],
                ),
                section(
                    "部署信息",
                    [
                        bullet("服务前缀", self.config.service_name_prefix, code=False),
                        bullet("工作目录", shorten_path(self.config.work_dir), code=False),
                        bullet("核心仓库", self.config.repo_url or "未设置", code=False),
                        bullet("插件目录", self.config.plugins_dir, code=False),
                        bullet("插件仓库", self.config.plugins_repo_url or "未设置", code=False),
                    ],
                ),
            ],
        )

    def render_status_message(self) -> str:
        runtime = self.db.get_runtime_stats()
        stats = self.collect_folder_stats()
        active_rows = []
        for item in stats["folder_cards"]:
            if not item["enabled"]:
                continue
            active_rows.append(f"· <b>{escape(item['folder_name'])}</b> · 群 <code>{item['cache_count']}</code> · 规则 <code>{item['rule_count']}</code>")
        if not active_rows:
            active_rows = ["· <i>当前没有开启监听的分组。</i>"]
        sections = [
            section(
                "总体统计",
                [
                    bullet("全部分组", stats["total_folders"]),
                    bullet("已启用分组", stats["enabled_folders"]),
                    bullet("全部群组缓存", stats["total_cached"]),
                    bullet("监听目标", stats["target_count"]),
                    bullet("规则总数", stats["total_rules"]),
                    bullet("生效规则", stats["valid_rules"]),
                    bullet("自动归纳规则", stats["route_count"]),
                    bullet("待处理归纳任务", stats["queue_size"]),
                    bullet("Admin 插件", len(self.plugin_manager.admin_states)),
                    bullet("Core 插件", len(self.plugin_manager.core_catalog)),
                ],
            ),
            section(
                "命中与运行",
                [
                    bullet("总命中次数", runtime.get("total_hits") or 0),
                    bullet("最近命中分组", runtime.get("last_hit_folder") or "暂无记录", code=False),
                    bullet("最近命中时间", runtime.get("last_hit_time") or "暂无记录", code=False),
                    bullet("最近同步", runtime.get("last_sync") or "未执行", code=False),
                    bullet("最近 Core 重载", runtime.get("last_core_reload") or "未记录", code=False),
                ],
            ),
            section("已启用分组", active_rows[:10]),
        ]
        if self._startup_sync_note:
            sections.append(section("启动前校准", [f"· {escape(self._startup_sync_note)}"]))
        return panel("TG-Radar 状态总览", sections)

    def render_folders_message(self) -> str:
        stats = self.collect_folder_stats()
        rows = []
        for item in stats["folder_cards"]:
            rows.append(
                "\n".join(
                    [
                        f"<b>{escape(item['folder_name'])}</b>",
                        bullet("状态", "开启" if item["enabled"] else "关闭", code=False),
                        bullet("folder_id", item["folder_id"] if item["folder_id"] is not None else "未同步", code=False),
                        bullet("缓存群组", item["cache_count"]),
                        bullet("规则数", item["rule_count"]),
                        bullet("告警目标", item["alert_channel_id"] if item["alert_channel_id"] is not None else "默认", code=False),
                    ]
                )
            )
        if not rows:
            rows = ["· <i>当前还没有任何分组记录。</i>"]
        return panel(
            "TG 分组总览",
            [
                section(
                    "汇总",
                    [
                        bullet("全部分组", stats["total_folders"]),
                        bullet("已启用分组", stats["enabled_folders"]),
                        bullet("全部群组缓存", stats["total_cached"]),
                        bullet("规则总数", stats["total_rules"]),
                    ],
                ),
                section("分组列表", rows),
            ],
        )

    def render_rules_message(self, folder: str) -> str:
        rows = self.db.get_rules_for_folder(folder)
        if not rows:
            return panel(f"{folder} 的规则面板", [section("当前状态", ["· <i>该分组还没有启用中的规则。</i>"])])
        blocks = []
        for row in rows:
            blocks.append("\n".join([f"<b>{escape(row['rule_name'])}</b>", bullet("表达式", row["pattern"]), bullet("更新时间", row["updated_at"], code=False)]))
        return panel(f"{folder} 的规则面板", [section("规则列表", blocks)])

    def render_routes_message(self) -> str:
        rows = self.db.list_routes()
        if not rows:
            return panel("自动归纳规则面板", [section("当前状态", ["· <i>当前没有自动归纳规则。</i>"])])
        blocks = []
        for row in rows:
            blocks.append("\n".join([f"<b>{escape(row['folder_name'])}</b>", bullet("匹配表达式", row["pattern"]), bullet("更新时间", row["updated_at"], code=False)]))
        return panel("自动归纳规则面板", [section("规则列表", blocks)])

    def render_jobs_message(self) -> str:
        rows = self.db.list_open_jobs(20)
        if not rows:
            return panel("后台任务队列", [section("当前状态", ["· <i>当前没有排队或执行中的后台任务。</i>"])])
        blocks = []
        for row in rows:
            trace = ""
            try:
                payload = json.loads(row["payload_json"] or "{}")
                trace = str(payload.get("trace") or "")
            except Exception:
                trace = ""
            blocks.append(
                f"<b>{escape(row['kind'])}</b>\n· 状态：<code>{escape(row['status'])}</code>\n· 优先级：<code>{row['priority']}</code>\n· 计划执行：<code>{escape(row['run_after'] or '立即')}</code>\n"
                + (f"· 跟踪号：<code>{escape(trace)}</code>\n" if trace else "")
                + f"· 更新时间：<code>{escape(row['updated_at'])}</code>"
            )
        return panel("后台任务队列", [section("排队 / 执行中", blocks)], "<i>重任务串行执行，避免拖慢前台命令。</i>")

    def render_log_message(self, limit: int = 15, scope: str = "important") -> str:
        rows = self.db.recent_logs_for_panel(limit=limit, scope=scope)
        if not rows:
            return panel("最近关键事件", [section("结果", ["· <i>目前还没有可展示的日志。</i>"])])
        blocks = []
        for row in rows:
            detail = row["detail"]
            if len(detail) > 120:
                detail = detail[:119] + "…"
            lines = [f"{row['icon']} <b>{escape(row['title'])}</b>", bullet("时间", row["created_at"], code=False), bullet("摘要", row["summary"], code=False)]
            if detail and detail != row["summary"]:
                lines.append(bullet("详情", detail, code=False))
            blocks.append("\n".join(lines))
        return panel("最近关键事件", [section("事件流", blocks)], f"<i>发送 <code>{escape(self.config.cmd_prefix)}log all 20</code> 可查看更完整的事件流。</i>")

    def render_version_message(self) -> str:
        return panel(
            "版本与架构信息",
            [
                section(
                    "当前版本",
                    [
                        bullet("版本号", __version__, code=False),
                        bullet("Admin 架构", "插件注册中心 + 后台任务总线", code=False),
                        bullet("Core 架构", "外部 Core 插件 + DB revision 热重载", code=False),
                        bullet("插件 API", "v1", code=False),
                    ],
                )
            ],
        )

    def render_sync_message(self, sync_report: SyncReport, route_report: RouteReport) -> str:
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
            route_rows.append("· <i>本次没有新增自动归纳动作。</i>")

        active_rows = [f"· <b>{escape(name)}</b> · <code>{cnt}</code> 个群 / 频道" for name, cnt in sync_report.active.items()] or ["· <i>当前没有读取到任何分组群数据。</i>"]

        status = "发现变动并已更新" if sync_report.has_changes or route_report.queued or route_report.created else "同步完成，数据无变动"
        return panel(
            "TG-Radar 手动同步报告",
            [
                section(
                    "执行摘要",
                    [
                        bullet("结果", status, code=False),
                        bullet("耗时", f"{sync_report.elapsed_seconds:.1f} 秒", code=False),
                        bullet("时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code=False),
                    ],
                ),
                section("分组变动", folder_rows),
                section("自动归纳", route_rows),
                section("当前规模", active_rows[:10]),
            ],
            f"<i>发现新分组后，发送 <code>{escape(self.config.cmd_prefix)}enable 分组名</code> 即可开启监听。</i>",
        )

    def should_bootstrap_startup_snapshot(self) -> bool:
        stats = self.collect_folder_stats()
        if not stats["total_folders"]:
            return True
        if any(item["folder_id"] is None for item in stats["folder_cards"]):
            return True
        return int(stats["total_cached"]) == 0

    async def bootstrap_startup_snapshot_if_needed(self) -> None:
        if not self.should_bootstrap_startup_snapshot():
            self._startup_sync_note = "启动前校准未触发：本地已有有效分组快照。"
            return
        if self.worker_client is None:
            self._startup_sync_note = "启动前校准跳过：worker client 未就绪。"
            return
        try:
            sync_report = await sync_dialog_folders(self.worker_client, self.db, self.config)
            self.last_sync_result = (sync_report, RouteReport(created=[], queued={}, matched_zero=[], already_in={}, errors={}))
            sync_snapshot_to_config(self.config.work_dir, self.db)
            self._startup_sync_note = f"已完成启动前校准：识别 {len(sync_report.active)} 个分组，缓存 {sum(sync_report.active.values())} 个群 / 频道。"
        except Exception as exc:
            self._startup_sync_note = f"启动前校准失败：{exc}"
            self.logger.warning("startup bootstrap sync failed: %s", exc)

    def queue_snapshot_flush(self) -> None:
        now = time.monotonic()
        if now - self._last_snapshot_queued_at < self.config.snapshot_flush_debounce_seconds:
            return
        self._last_snapshot_queued_at = now
        self.command_bus.submit(
            "config_snapshot_flush",
            priority=220,
            dedupe_key="config_snapshot_flush",
            origin="system",
            visible=False,
            delay_seconds=self.config.snapshot_flush_debounce_seconds,
        )

    def queue_core_reload(self, reason: str, detail: str = "") -> None:
        self.command_bus.submit(
            "reload_core",
            payload={"reason": reason, "detail": detail},
            priority=40,
            dedupe_key="reload_core",
            origin="system",
            visible=False,
            delay_seconds=self.config.reload_debounce_seconds,
        )

    async def after_job(self, job: AdminJob, result: JobResult) -> None:
        assert self.message_io is not None
        reply_to = int(job.payload.get("reply_to") or 0)
        if job.kind == "sync_manual":
            sync_report, route_report = self.last_sync_result or (None, None)
            if sync_report is not None and route_report is not None and reply_to:
                await self.message_io.reply_to_message_id(reply_to, self.render_sync_message(sync_report, route_report), auto_delete=0)
            return
        if job.kind == "sync_auto" and result.notify:
            sync_report, route_report = self.last_sync_result or (None, None)
            if sync_report is not None and route_report is not None:
                await self.send_sync_report(sync_report, route_report, automatic=True)
            return
        if job.kind == "route_scan":
            route_report = (result.payload or {}).get("route_report")
            if reply_to and route_report is not None:
                queued = sum(route_report.queued.values())
                created = len(route_report.created)
                await self.message_io.reply_to_message_id(
                    reply_to,
                    panel(
                        "自动归纳扫描完成",
                        [section("执行结果", [bullet("新建分组", created), bullet("排队补群", queued), bullet("空结果规则", len(route_report.matched_zero)), bullet("错误数量", len(route_report.errors))])],
                    ),
                    auto_delete=0,
                )
            return
        if job.kind == "update_repo":
            title = "代码更新完成" if result.status == "done" else "代码更新失败"
            footer = f"<i>如需加载最新代码，请继续执行 <code>{escape(self.config.cmd_prefix)}restart</code>。</i>" if result.status == "done" else None
            if reply_to:
                await self.message_io.reply_to_message_id(reply_to, panel(title, [section("执行结果", [blockquote_preview(result.detail or result.summary, 1400)])], footer), auto_delete=0)
            return
        if job.kind == "restart_services":
            if reply_to:
                await self.message_io.reply_to_message_id(
                    reply_to,
                    panel("TG-Radar 即将重启", [section("调度层", ["· 重启指令已经下发给 systemd", "· Admin / Core 会自动重新拉起", "· 未完成的自动归纳任务会继续保留"])]),
                    auto_delete=0,
                )
            return

    async def notify_job_failure(self, job: AdminJob, exc: Exception) -> None:
        assert self.message_io is not None
        reply_to = int(job.payload.get("reply_to") or 0)
        if reply_to:
            await self.message_io.reply_to_message_id(
                reply_to,
                panel(
                    "后台任务执行失败",
                    [section("异常说明", [blockquote_preview(str(exc), 500)])],
                    "<i>详细堆栈已写入 admin.log，可在终端执行 <code>TR logs admin</code> 排查。</i>",
                ),
                auto_delete=0,
            )

    async def apply_route_task(self, task: RouteTask) -> None:
        assert self.worker_client is not None
        req = await self.worker_client(functions.messages.GetDialogFiltersRequest())
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
                peers.append(await self.worker_client.get_input_entity(peer_id))
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
            await self.worker_client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=new_filter))
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
        await self.worker_client(functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target))

    async def send_sync_report(self, sync_report: SyncReport, route_report: RouteReport, automatic: bool = False) -> None:
        assert self.message_io is not None
        target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "me"
        title = "TG-Radar 自动同步报告" if automatic else "TG-Radar 手动同步报告"
        message = self.render_sync_message(sync_report, route_report).replace("TG-Radar 手动同步报告", title, 1)
        try:
            await self.message_io.notify(target, message, auto_delete=0)
        except Exception as exc:
            self.logger.warning("send sync report failed: %s", exc)

    async def send_startup_notification(self) -> None:
        assert self.command_client is not None
        stats = self.collect_folder_stats()
        folder_rows = []
        for item in stats["folder_cards"][:12]:
            folder_rows.append(
                f"· <b>{escape(item['folder_name'])}</b> · 状态 {escape('开启' if item['enabled'] else '关闭')} · 群 <code>{item['cache_count']}</code> · 规则 <code>{item['rule_count']}</code>"
            )
        if not folder_rows:
            folder_rows = ["· <i>当前没有分组记录。</i>"]
        route_rows = [f"· <code>{escape(row['pattern'])}</code> → <code>{escape(row['folder_name'])}</code>" for row in self.db.list_routes()[:10]] or ["· <i>当前没有自动归纳规则。</i>"]
        sections = [
            section(
                "运行概况",
                [
                    bullet("架构", "Plugin Core / Admin + Core / SQLite WAL", code=False),
                    bullet("版本", __version__, code=False),
                    bullet("启动时间", self.started_at.strftime("%Y-%m-%d %H:%M:%S"), code=False),
                    bullet("自动同步", f"每日 {self.config.auto_sync_time}" if self.config.auto_sync_enabled else "已关闭", code=False),
                    bullet("热重载", "DB revision + 信号双通道", code=False),
                ],
            ),
            section(
                "规模统计",
                [
                    bullet("全部分组", stats["total_folders"]),
                    bullet("已启用分组", stats["enabled_folders"]),
                    bullet("全部群组缓存", stats["total_cached"]),
                    bullet("已启用分组缓存", stats["enabled_cached"]),
                    bullet("监听目标", stats["target_count"]),
                    bullet("规则总数", stats["total_rules"]),
                    bullet("生效规则", stats["valid_rules"]),
                    bullet("自动归纳规则", stats["route_count"]),
                    bullet("Admin 插件", len(self.plugin_manager.admin_states)),
                    bullet("Core 插件", len(self.plugin_manager.core_catalog)),
                ],
            ),
            section("分组总览", folder_rows),
            section("自动归纳规则", route_rows),
        ]
        if self._startup_sync_note:
            sections.append(section("启动前校准", [f"· {escape(self._startup_sync_note)}"]))
        startup_card = panel("TG-Radar 已上线", sections, f"<i>在收藏夹发送 <code>{escape(self.config.cmd_prefix)}help</code> 可以打开插件化管理面板。</i>")

        last_msg_path = self.config.work_dir / ".last_msg"
        msg_obj = None
        if last_msg_path.exists():
            try:
                ctx = json.loads(last_msg_path.read_text(encoding="utf-8"))
                action = ctx.get("action", "restart")
                prefix_text = "✨ <b>代码更新完成</b>\n\n" if action == "update" else "🔄 <b>服务重启完成</b>\n\n"
                msg_obj = await self.command_client.edit_message("me", int(ctx["msg_id"]), prefix_text + startup_card)
                last_msg_path.unlink(missing_ok=True)
                self.try_log_event("INFO", "RESTORE", f"system back online after {action}")
            except Exception:
                msg_obj = None
        if msg_obj is None:
            target = self.config.notify_channel_id if self.config.notify_channel_id is not None else "me"
            try:
                await self.command_client.send_message(target, startup_card, link_preview=False)
            except Exception as exc:
                self.logger.warning("startup notification failed: %s", exc)

    def _make_trace_id(self) -> str:
        return datetime.now().strftime("cmd-%m%d-%H%M%S-%f")[:-3]

    async def is_saved_messages_command(self, event: events.NewMessage.Event) -> bool:
    if not getattr(event, "is_private", False):
        return False

    # 先走本地自聊判断，不依赖网络，也不要求 event.out
    try:
        chat_id = int(getattr(event, "chat_id", 0) or 0)
        sender_id = int(getattr(event, "sender_id", 0) or 0)
        if self.self_id and chat_id == self.self_id and sender_id == self.self_id:
            return True
    except Exception:
        pass

    # 再做远程兜底，避免 get_chat 卡住
    try:
        chat = await asyncio.wait_for(event.get_chat(), timeout=1.5)
        return bool(getattr(chat, "self", False))
    except Exception:
        return False

    async def dispatch_command(self, event: events.NewMessage.Event, command: str, args: str, trace: str) -> None:
        spec = self.registry.get(command)
        if spec is None:
            await self.reply_panel(event, panel("未知命令", [section("提示", [f"· 发送 <code>{escape(self.config.cmd_prefix)}help</code> 查看帮助。"])]), auto_delete=0)
            return
        ctx = CommandContext(app=self, event=event, command=command, args=args, tokens=self.parse_tokens(args), trace=trace)
        await spec.handler(ctx)
        self.try_log_event("INFO", "CMD_ACCEPTED", f"{trace} {command} {args[:160]}")

    def register_handlers(self, client: TelegramClient) -> None:
        @client.on(events.NewMessage)
        async def control_panel(event: events.NewMessage.Event) -> None:
            text = (event.raw_text or "").strip()
            if not text or not text.startswith(self.config.cmd_prefix):
                return
            if not await self.is_saved_messages_command(event):
                return
            match = re.match(rf"^{re.escape(self.config.cmd_prefix)}(\w+)[ \t]*([\s\S]*)", text, re.IGNORECASE)
            if not match:
                return
            command = match.group(1).lower()
            args = (match.group(2) or "").strip()
            trace = self._make_trace_id()
            self.last_command_ts = time.monotonic()
            try:
                await self.dispatch_command(event, command, args, trace)
            except Exception as exc:
                self.logger.exception("command failed trace=%s: %s", trace, exc)
                self.try_log_event("ERROR", "COMMAND", f"{trace} {exc}")
                await self.reply_panel(
                    event,
                    panel(
                        "TG-Radar 命令执行异常",
                        [section("异常说明", [blockquote_preview(str(exc), 500)]), section("定位信息", [bullet("跟踪号", trace, code=False)])],
                        "<i>详细堆栈已写入 admin.log，可在终端执行 <code>TR logs admin</code> 排查。</i>",
                    ),
                    auto_delete=0,
                )

    def restart_services(self, delay: float = 0.0) -> None:
        cmd = ["bash", "-lc", f"sleep {delay}; systemctl restart {self.config.service_name_prefix}-core {self.config.service_name_prefix}-admin"]
        subprocess.Popen(cmd)

    def write_last_message(self, msg_id: int, action: str) -> None:
        path = self.config.work_dir / ".last_msg"
        path.write_text(json.dumps({"chat_id": "me", "msg_id": msg_id, "action": action}, ensure_ascii=False), encoding="utf-8")

    async def run(self) -> None:
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)
        admin_session = self.config.admin_session.with_suffix(".session")
        worker_session = self.config.admin_worker_session.with_suffix(".session")
        if not admin_session.exists():
            raise FileNotFoundError("Missing runtime/sessions/tg_radar_admin.session. Run bootstrap_session.py first.")
        if not worker_session.exists():
            try:
                import shutil

                shutil.copy2(admin_session, worker_session)
            except Exception:
                raise FileNotFoundError("Missing runtime/sessions/tg_radar_admin_worker.session. Run bootstrap_session.py again.")

        lock_file = self.config.work_dir / ".admin.lock"
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        try:
            if os.name != "nt":
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            raise RuntimeError("tg-radar-admin is already running")

        async with TelegramClient(str(self.config.admin_session), self.config.api_id, self.config.api_hash) as command_client, TelegramClient(str(self.config.admin_worker_session), self.config.api_id, self.config.api_hash) as worker_client:
            self.command_client = command_client
            self.worker_client = worker_client
            self.client = worker_client
            self.message_io = MessageIO(command_client)
            command_client.parse_mode = "html"
            worker_client.parse_mode = "html"
            me = await command_client.get_me()
            self.self_id = int(getattr(me, "id", 0) or 0)
            await self.reload_admin_plugins()
            self.register_handlers(command_client)
            await self.bootstrap_startup_snapshot_if_needed()
            self.try_log_event("INFO", "ADMIN", f"TG-Radar admin started v{__version__}")
            await self.send_startup_notification()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.stop_event.set)
                except NotImplementedError:
                    pass

            self.scheduler = AdminScheduler(self)
            tasks = [
                asyncio.create_task(self.scheduler.run()),
                asyncio.create_task(command_client.run_until_disconnected()),
                asyncio.create_task(self.stop_event.wait()),
            ]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            self.stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.try_log_event("INFO", "ADMIN", "admin service stopping")
            self.logger.info("TG-Radar admin service stopping")


async def run(work_dir: Path) -> None:
    app = AdminApp(work_dir)
    await app.run()
