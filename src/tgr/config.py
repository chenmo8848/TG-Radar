from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "api_id": 1234567,
    "api_hash": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "global_alert_channel_id": None,
    "notify_channel_id": None,
    "cmd_prefix": "-",
    "service_name_prefix": "tg-radar",
    "sync_interval_seconds": 60,
    "route_worker_interval_seconds": 4,
    "revision_poll_seconds": 3,
    "panel_auto_delete_seconds": 45,
    "notify_auto_delete_seconds": 90,
    "recycle_fallback_command_seconds": 8,
    "repo_url": "https://github.com/chenmo8848/TG-Radar.git",
    "auto_route_rules": {},
    "folder_rules": {},
    "_system_cache": {},
}


@dataclass(frozen=True)
class AppConfig:
    work_dir: Path
    api_id: int
    api_hash: str
    global_alert_channel_id: int | None
    notify_channel_id: int | None
    cmd_prefix: str
    service_name_prefix: str
    sync_interval_seconds: int
    route_worker_interval_seconds: int
    revision_poll_seconds: int
    panel_auto_delete_seconds: int
    notify_auto_delete_seconds: int
    recycle_fallback_command_seconds: int
    repo_url: str | None

    @property
    def runtime_dir(self) -> Path:
        return self.work_dir / "runtime"

    @property
    def db_path(self) -> Path:
        return self.runtime_dir / "radar.db"

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def sessions_dir(self) -> Path:
        return self.runtime_dir / "sessions"

    @property
    def backups_dir(self) -> Path:
        return self.runtime_dir / "backups"

    @property
    def admin_session(self) -> Path:
        return self.sessions_dir / "tg_radar_admin"

    @property
    def core_session(self) -> Path:
        return self.sessions_dir / "tg_radar_core"


def _normalize_int(value: Any) -> int | None:
    if value in (None, "", "null", "None", "off", "OFF"):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _normalize_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        normalized = int(str(value).strip())
    except Exception:
        normalized = default
    return max(minimum, normalized)


def read_config_data(work_dir: Path) -> dict[str, Any]:
    path = work_dir / "config.json"
    raw: dict[str, Any]
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = {}

    data = dict(DEFAULT_CONFIG)
    data.update(raw)
    data["api_id"] = int(data.get("api_id") or 0)
    data["api_hash"] = str(data.get("api_hash") or "")
    data["global_alert_channel_id"] = _normalize_int(data.get("global_alert_channel_id"))
    data["notify_channel_id"] = _normalize_int(data.get("notify_channel_id"))
    data["cmd_prefix"] = str(data.get("cmd_prefix") or "-")
    data["service_name_prefix"] = str(data.get("service_name_prefix") or "tg-radar")
    data["sync_interval_seconds"] = _normalize_positive_int(data.get("sync_interval_seconds"), 60, 10)
    data["route_worker_interval_seconds"] = _normalize_positive_int(data.get("route_worker_interval_seconds"), 4, 1)
    data["revision_poll_seconds"] = _normalize_positive_int(data.get("revision_poll_seconds"), 3, 1)
    data["panel_auto_delete_seconds"] = _normalize_positive_int(data.get("panel_auto_delete_seconds"), 45, 0)
    data["notify_auto_delete_seconds"] = _normalize_positive_int(data.get("notify_auto_delete_seconds"), 90, 0)
    data["recycle_fallback_command_seconds"] = _normalize_positive_int(data.get("recycle_fallback_command_seconds"), 8, 0)
    data["repo_url"] = str(data.get("repo_url") or DEFAULT_CONFIG["repo_url"])
    data["auto_route_rules"] = data.get("auto_route_rules") or {}
    data["folder_rules"] = data.get("folder_rules") or {}
    data["_system_cache"] = data.get("_system_cache") or {}
    return data


def _descriptive_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "_说明_1": "👇【核心通信凭证】前往 my.telegram.org 获取，切勿泄露",
        "api_id": data.get("api_id", 1234567),
        "api_hash": data.get("api_hash", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),
        "_说明_2": "👇【消息流转设置】global_alert 为默认告警频道，notify 为系统通知频道（留 null 则发给收藏夹）",
        "global_alert_channel_id": data.get("global_alert_channel_id"),
        "notify_channel_id": data.get("notify_channel_id"),
        "_说明_3": "👇【交互控制台】在 Telegram 收藏夹中触发命令的前缀，默认是减号 -",
        "cmd_prefix": data.get("cmd_prefix", "-"),
        "_说明_4": "👇【服务与轮询参数】一般无需修改；panel/notify 为 Telegram 面板与通知的自动回收秒数",
        "service_name_prefix": data.get("service_name_prefix", "tg-radar"),
        "sync_interval_seconds": data.get("sync_interval_seconds", 60),
        "route_worker_interval_seconds": data.get("route_worker_interval_seconds", 4),
        "revision_poll_seconds": data.get("revision_poll_seconds", 3),
        "panel_auto_delete_seconds": data.get("panel_auto_delete_seconds", 45),
        "notify_auto_delete_seconds": data.get("notify_auto_delete_seconds", 90),
        "recycle_fallback_command_seconds": data.get("recycle_fallback_command_seconds", 8),
        "repo_url": data.get("repo_url", DEFAULT_CONFIG["repo_url"]),
        "_说明_5": "👇【智能收纳路由】只要加入的新群名符合规则，系统会自动把它拉入对应 TG 分组",
        "auto_route_rules": data.get("auto_route_rules", {}),
        "_说明_6": "👇【系统生成区】雷达会把规则和群组拓扑实时写回这里，请通过 Telegram 命令修改，不建议手改",
        "folder_rules": data.get("folder_rules", {}),
        "_system_cache": data.get("_system_cache", {}),
    }


def save_config_data(work_dir: Path, data: dict[str, Any]) -> Path:
    config_path = work_dir / "config.json"
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(data)
    payload = _descriptive_payload(normalized)
    tmp = config_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    tmp.replace(config_path)
    return config_path


def update_config_data(work_dir: Path, updates: dict[str, Any]) -> Path:
    data = read_config_data(work_dir)
    data.update(updates)
    return save_config_data(work_dir, data)


def load_config(work_dir: Path) -> AppConfig:
    data = read_config_data(work_dir)
    api_id = int(data.get("api_id") or 0)
    api_hash = str(data.get("api_hash") or "")
    if not api_id or api_id == 1234567 or not api_hash or api_hash == "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx":
        raise ValueError("config.json does not contain valid Telegram API credentials")

    cfg = AppConfig(
        work_dir=work_dir,
        api_id=api_id,
        api_hash=api_hash,
        global_alert_channel_id=data.get("global_alert_channel_id"),
        notify_channel_id=data.get("notify_channel_id"),
        cmd_prefix=str(data.get("cmd_prefix") or "-"),
        service_name_prefix=str(data.get("service_name_prefix") or "tg-radar"),
        sync_interval_seconds=_normalize_positive_int(data.get("sync_interval_seconds"), 60, 10),
        route_worker_interval_seconds=_normalize_positive_int(data.get("route_worker_interval_seconds"), 4, 1),
        revision_poll_seconds=_normalize_positive_int(data.get("revision_poll_seconds"), 3, 1),
        panel_auto_delete_seconds=_normalize_positive_int(data.get("panel_auto_delete_seconds"), 45, 0),
        notify_auto_delete_seconds=_normalize_positive_int(data.get("notify_auto_delete_seconds"), 90, 0),
        recycle_fallback_command_seconds=_normalize_positive_int(data.get("recycle_fallback_command_seconds"), 8, 0),
        repo_url=data.get("repo_url") or None,
    )
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.sessions_dir.mkdir(parents=True, exist_ok=True)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def sync_snapshot_to_config(work_dir: Path, db: object) -> None:
    data = read_config_data(work_dir)
    if hasattr(db, "export_legacy_snapshot"):
        snapshot = db.export_legacy_snapshot()
        data["folder_rules"] = snapshot.get("folder_rules", {})
        data["_system_cache"] = snapshot.get("_system_cache", {})
        data["auto_route_rules"] = snapshot.get("auto_route_rules", {})
    save_config_data(work_dir, data)
