from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLUGIN_API_VERSION = "1"


@dataclass(slots=True)
class PluginState:
    name: str
    display_name: str
    version: str
    description: str
    mode: str
    source: str
    path: str
    status: str
    commands: list[str] = field(default_factory=list)
    error: str = ""
    health_status: str = "unknown"
    health_summary: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
