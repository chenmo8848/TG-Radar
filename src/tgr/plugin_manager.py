from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from .plugin_api import PLUGIN_API_VERSION, PluginState


class PluginManager:
    def __init__(self, work_dir: Path, config: Any, logger=None) -> None:
        self.work_dir = work_dir
        self.config = config
        self.logger = logger
        self.admin_states: list[PluginState] = []
        self.core_catalog: list[PluginState] = []
        self.core_states: list[PluginState] = []

    @property
    def external_root(self) -> Path:
        raw = getattr(self.config, "plugins_dir", None) or "./plugins-external/TG-Radar-Plugins"
        root = Path(raw)
        if not root.is_absolute():
            root = (self.work_dir / root).resolve()
        return root

    def _state_from_module(self, module: Any, *, default_name: str, mode: str, path: str, source: str) -> PluginState:
        meta = dict(getattr(module, "PLUGIN_META", {}) or {})
        return PluginState(
            name=str(meta.get("name") or default_name),
            display_name=str(meta.get("display_name") or meta.get("name") or default_name),
            version=str(meta.get("version") or "0.1.0"),
            description=str(meta.get("description") or ""),
            mode=str(meta.get("mode") or mode),
            source=source,
            path=path,
            status="loaded",
            commands=[],
            meta=meta,
        )

    def _load_file_module(self, path: Path, unique_tag: str) -> Any:
        module_name = f"tgr_ext_{path.stem}_{unique_tag}_{int(path.stat().st_mtime_ns)}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load plugin spec from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _iter_external(self, mode: str) -> list[Path]:
        root = self.external_root / "plugins" / mode
        if not root.exists():
            return []
        return sorted([p for p in root.glob("*.py") if p.is_file() and not p.name.startswith("_")])

    def load_admin_plugins(self, registry) -> list[PluginState]:
        registry.clear()
        states: list[PluginState] = []
        builtin_modules = [
            "tgr.builtin_plugins.admin.general",
            "tgr.builtin_plugins.admin.plugins",
        ]
        for mod_name in builtin_modules:
            before = {spec.name for spec in registry.unique_specs()}
            try:
                module = importlib.reload(importlib.import_module(mod_name))
                state = self._state_from_module(module, default_name=mod_name.rsplit(".", 1)[-1], mode="admin", path=mod_name, source="builtin")
                register = getattr(module, "register", None)
                if not callable(register):
                    raise RuntimeError("missing register(registry)")
                register(registry)
                state.commands = sorted({spec.name for spec in registry.unique_specs()} - before)
                state.health_status = "ok"
            except Exception as exc:
                state = PluginState(name=mod_name.rsplit(".", 1)[-1], display_name=mod_name.rsplit(".", 1)[-1], version="0", description="", mode="admin", source="builtin", path=mod_name, status="failed", error=str(exc), health_status="error", health_summary=str(exc))
            states.append(state)

        for path in self._iter_external("admin"):
            before = {spec.name for spec in registry.unique_specs()}
            try:
                module = self._load_file_module(path, "admin")
                state = self._state_from_module(module, default_name=path.stem, mode="admin", path=str(path), source="external")
                if str(state.meta.get("api_version") or PLUGIN_API_VERSION) != PLUGIN_API_VERSION:
                    raise RuntimeError(f"plugin api mismatch: expected {PLUGIN_API_VERSION}")
                register = getattr(module, "register", None)
                if not callable(register):
                    raise RuntimeError("missing register(registry)")
                register(registry)
                state.commands = sorted({spec.name for spec in registry.unique_specs()} - before)
            except Exception as exc:
                state = PluginState(name=path.stem, display_name=path.stem, version="0", description="", mode="admin", source="external", path=str(path), status="failed", error=str(exc), health_status="error", health_summary=str(exc))
            states.append(state)

        state_map = {state.name: state for state in states}
        for spec in registry.unique_specs():
            state = state_map.get(spec.plugin)
            if state is not None:
                spec.plugin_display = state.display_name
                spec.plugin_description = state.description
        self.admin_states = states
        self.core_catalog = self.discover_catalog("core")
        return states

    def discover_catalog(self, mode: str) -> list[PluginState]:
        states: list[PluginState] = []
        for path in self._iter_external(mode):
            try:
                module = self._load_file_module(path, f"catalog_{mode}")
                state = self._state_from_module(module, default_name=path.stem, mode=mode, path=str(path), source="external")
                state.status = "discovered"
            except Exception as exc:
                state = PluginState(name=path.stem, display_name=path.stem, version="0", description="", mode=mode, source="external", path=str(path), status="failed", error=str(exc), health_status="error", health_summary=str(exc))
            states.append(state)
        return states

    def load_core_plugins(self) -> list[PluginState]:
        states: list[PluginState] = []
        for path in self._iter_external("core"):
            try:
                module = self._load_file_module(path, "core")
                state = self._state_from_module(module, default_name=path.stem, mode="core", path=str(path), source="external")
                state.meta["module"] = module
                state.health_status = "ok"
            except Exception as exc:
                state = PluginState(name=path.stem, display_name=path.stem, version="0", description="", mode="core", source="external", path=str(path), status="failed", error=str(exc), health_status="error", health_summary=str(exc))
            states.append(state)
        self.core_states = states
        return states

    async def refresh_admin_health(self, app) -> None:
        for state in self.admin_states:
            if state.status != "loaded" or state.source != "external":
                state.health_status = "ok" if state.status == "loaded" else "error"
                continue
            try:
                module = self._load_file_module(Path(state.path), "health_admin")
                checker = getattr(module, "healthcheck", None)
                if checker is None:
                    state.health_status = "ok"
                    state.health_summary = "未声明健康检查"
                    continue
                result = checker(app)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict):
                    state.health_status = str(result.get("status") or "ok")
                    state.health_summary = str(result.get("summary") or "")
                else:
                    state.health_status = "ok"
                    state.health_summary = str(result)
            except Exception as exc:
                state.health_status = "error"
                state.health_summary = str(exc)

    async def call_core_hook(self, hook: str, app, *args) -> None:
        for state in self.core_states:
            if state.status != "loaded":
                continue
            module = state.meta.get("module")
            if module is None:
                continue
            func = getattr(module, hook, None)
            if func is None:
                continue
            try:
                result = func(app, *args)
                if inspect.isawaitable(result):
                    await result
                state.health_status = "ok"
            except Exception as exc:
                state.health_status = "error"
                state.health_summary = str(exc)
                if self.logger:
                    self.logger.exception("core plugin hook failed name=%s hook=%s: %s", state.name, hook, exc)

    def core_runtime_snapshot(self, runtime: dict[str, str]) -> list[dict[str, str]]:
        out = []
        for state in self.core_catalog:
            prefix = f"plugin.core.{state.name}."
            out.append(
                {
                    "name": state.name,
                    "display_name": state.display_name,
                    "description": state.description,
                    "version": state.version,
                    "status": runtime.get(prefix + "status", state.status),
                    "summary": runtime.get(prefix + "summary", ""),
                    "revision": runtime.get(prefix + "revision", ""),
                    "chats": runtime.get(prefix + "chats", ""),
                    "rules": runtime.get(prefix + "rules", ""),
                    "last_reload": runtime.get(prefix + "last_reload", ""),
                }
            )
        return out
