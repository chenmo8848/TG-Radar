from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable


CommandHandler = Callable[[Any, Any, str], Awaitable[None]]
MessageHook = Callable[[Any, Any], Awaitable[None]]
HealthCheck = Callable[[Any], Awaitable[tuple[str, str] | str] | tuple[str, str] | str]


@dataclass
class CommandSpec:
    name: str
    handler: CommandHandler
    plugin_name: str
    summary: str
    usage: str
    category: str = "通用"
    aliases: tuple[str, ...] = ()
    heavy: bool = False
    hidden: bool = False


@dataclass
class HookSpec:
    name: str
    handler: MessageHook
    plugin_name: str
    summary: str
    order: int = 100


@dataclass
class PluginRecord:
    name: str
    kind: str
    source: str
    path: str
    version: str = "0.1.0"
    description: str = ""
    loaded: bool = False
    enabled: bool = True
    load_error: str | None = None
    commands: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    run_count: int = 0
    fail_count: int = 0
    last_error: str | None = None
    last_run_at: str | None = None
    last_health: str = "unknown"
    last_health_detail: str = "未执行"
    healthcheck: HealthCheck | None = None

    def mark_success(self) -> None:
        self.run_count += 1
        self.last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_error = None

    def mark_failure(self, exc: Exception) -> None:
        self.fail_count += 1
        self.last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_error = str(exc)


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def clear(self) -> None:
        self._commands.clear()

    def register(self, spec: CommandSpec) -> None:
        keys = [spec.name.lower(), *[alias.lower() for alias in spec.aliases]]
        for key in keys:
            self._commands[key] = spec

    def get(self, name: str) -> CommandSpec | None:
        return self._commands.get(name.lower())

    def all(self) -> list[CommandSpec]:
        seen: set[tuple[str, str]] = set()
        ordered: list[CommandSpec] = []
        for spec in self._commands.values():
            key = (spec.plugin_name, spec.name)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(spec)
        ordered.sort(key=lambda item: (item.category, item.name))
        return ordered


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: list[HookSpec] = []

    def clear(self) -> None:
        self._hooks.clear()

    def register(self, spec: HookSpec) -> None:
        self._hooks.append(spec)
        self._hooks.sort(key=lambda item: (item.order, item.name))

    def all(self) -> list[HookSpec]:
        return list(self._hooks)


class PluginContext:
    def __init__(self, manager: "PluginManager", plugin: PluginRecord, kind: str) -> None:
        self.manager = manager
        self.app = manager.app
        self.plugin = plugin
        self.kind = kind

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        *,
        summary: str,
        usage: str,
        category: str = "通用",
        aliases: tuple[str, ...] = (),
        heavy: bool = False,
        hidden: bool = False,
    ) -> None:
        async def wrapped(app: Any, event: Any, args: str) -> None:
            try:
                await handler(app, event, args)
                self.plugin.mark_success()
            except Exception as exc:
                self.plugin.mark_failure(exc)
                raise

        spec = CommandSpec(
            name=name,
            handler=wrapped,
            plugin_name=self.plugin.name,
            summary=summary,
            usage=usage,
            category=category,
            aliases=aliases,
            heavy=heavy,
            hidden=hidden,
        )
        self.manager.command_registry.register(spec)
        self.plugin.commands.append(name)

    def register_message_hook(
        self,
        name: str,
        handler: MessageHook,
        *,
        summary: str,
        order: int = 100,
    ) -> None:
        async def wrapped(app: Any, event: Any) -> None:
            try:
                await handler(app, event)
                self.plugin.mark_success()
            except Exception as exc:
                self.plugin.mark_failure(exc)
                raise

        spec = HookSpec(name=name, handler=wrapped, plugin_name=self.plugin.name, summary=summary, order=order)
        self.manager.hook_registry.register(spec)
        self.plugin.hooks.append(name)

    def set_healthcheck(self, func: HealthCheck) -> None:
        self.plugin.healthcheck = func


class PluginManager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.command_registry = CommandRegistry()
        self.hook_registry = HookRegistry()
        self.admin_plugins: dict[str, PluginRecord] = {}
        self.core_plugins: dict[str, PluginRecord] = {}
        self.load_errors: list[str] = []

    def _module_name(self, base: str, file_path: Path) -> str:
        safe = "_".join(file_path.with_suffix("").parts)
        return f"tgr_dynamic_{base}_{safe}"

    def _iter_plugin_files(self, root: Path, kind: str) -> list[Path]:
        target = root / kind
        if not target.exists():
            return []
        return sorted([p for p in target.rglob("*.py") if p.is_file() and p.name != "__init__.py"])

    def _load_from_dir(self, root: Path, kind: str, source: str) -> None:
        if not root.exists():
            return
        for file_path in self._iter_plugin_files(root, kind):
            plugin_name = file_path.stem
            record = PluginRecord(name=plugin_name, kind=kind, source=source, path=str(file_path))
            store = self.admin_plugins if kind == "admin" else self.core_plugins
            store[plugin_name] = record
            try:
                module_name = self._module_name(kind, file_path)
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"无法加载插件文件: {file_path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                meta = getattr(module, "PLUGIN_META", {}) or {}
                record.version = str(meta.get("version") or record.version)
                record.description = str(meta.get("description") or meta.get("display_name") or plugin_name)
                ctx = PluginContext(self, record, kind)
                setup = getattr(module, "setup", None) or getattr(module, "register", None)
                if setup is None:
                    raise RuntimeError("插件缺少 setup(ctx) 入口")
                setup(ctx)
                record.loaded = True
            except Exception as exc:
                record.load_error = str(exc)
                self.load_errors.append(f"{kind}:{plugin_name}: {exc}")

    def _builtin_root(self) -> Path:
        return Path(__file__).resolve().parent.parent / "builtin_plugins"

    def _external_root(self) -> Path:
        return getattr(self.app.config, 'plugins_root')

    def load_admin_plugins(self) -> None:
        self.command_registry.clear()
        self.admin_plugins.clear()
        self.load_errors.clear()
        builtin_root = self._builtin_root()
        self._load_from_dir(builtin_root, "admin", "builtin")
        self._load_from_dir(self._external_root(), "admin", "external")

    def load_core_plugins(self) -> None:
        self.hook_registry.clear()
        self.core_plugins.clear()
        self.load_errors.clear()
        builtin_root = self._builtin_root()
        self._load_from_dir(builtin_root, "core", "builtin")
        self._load_from_dir(self._external_root(), "core", "external")

    async def dispatch_admin_command(self, name: str, app: Any, event: Any, args: str) -> bool:
        spec = self.command_registry.get(name)
        if spec is None:
            return False
        await spec.handler(app, event, args)
        return True

    def is_heavy_command(self, name: str) -> bool:
        spec = self.command_registry.get(name)
        return bool(spec.heavy) if spec else False

    async def process_core_message(self, app: Any, event: Any) -> None:
        for hook in self.hook_registry.all():
            await hook.handler(app, event)

    def list_plugins(self, kind: str | None = None) -> list[PluginRecord]:
        records: list[PluginRecord] = []
        if kind in (None, "admin"):
            records.extend(self.admin_plugins.values())
        if kind in (None, "core"):
            records.extend(self.core_plugins.values())
        return sorted(records, key=lambda item: (item.kind, item.name))

    async def run_healthchecks(self) -> None:
        for record in self.list_plugins():
            if record.healthcheck is None:
                record.last_health = "unknown"
                record.last_health_detail = "未提供健康检查"
                continue
            try:
                result = record.healthcheck(self.app)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, tuple):
                    status, detail = result
                else:
                    status, detail = "ok", str(result)
                record.last_health = str(status)
                record.last_health_detail = str(detail)
            except Exception as exc:
                record.last_health = "error"
                record.last_health_detail = str(exc)
                record.last_error = str(exc)
