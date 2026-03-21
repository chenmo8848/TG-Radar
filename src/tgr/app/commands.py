from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass(slots=True)
class CommandContext:
    app: object
    event: object
    command: str
    args: str
    tokens: list[str]
    trace: str


CommandHandler = Callable[[CommandContext], Awaitable[None]]


@dataclass(slots=True)
class CommandSpec:
    name: str
    handler: CommandHandler
    summary: str
    usage: str
    heavy: bool = False
    category: str = "general"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    plugin: str = ""
    plugin_display: str = ""
    plugin_description: str = ""


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def clear(self) -> None:
        self._commands.clear()

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec
        for alias in spec.aliases:
            self._commands[alias] = spec

    def command(
        self,
        name: str,
        *,
        summary: str,
        usage: str,
        heavy: bool = False,
        aliases: tuple[str, ...] = (),
        category: str = "general",
        plugin: str = "",
        plugin_display: str = "",
        plugin_description: str = "",
    ):
        def decorator(func: CommandHandler) -> CommandHandler:
            self.register(
                CommandSpec(
                    name=name,
                    handler=func,
                    summary=summary,
                    usage=usage,
                    heavy=heavy,
                    aliases=aliases,
                    category=category,
                    plugin=plugin or category,
                    plugin_display=plugin_display,
                    plugin_description=plugin_description,
                )
            )
            return func

        return decorator

    def get(self, name: str) -> CommandSpec | None:
        return self._commands.get(name)

    def unique_specs(self) -> list[CommandSpec]:
        seen: set[str] = set()
        out: list[CommandSpec] = []
        for spec in self._commands.values():
            if spec.name in seen:
                continue
            seen.add(spec.name)
            out.append(spec)
        return sorted(out, key=lambda item: (item.plugin_display or item.plugin, item.category, item.name))
