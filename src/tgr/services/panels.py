from __future__ import annotations

from ..app.commands import CommandSpec
from ..plugin_api import PluginState
from ..telegram_utils import bullet, escape, panel, section


def render_help_panel(prefix: str, specs: list[CommandSpec], states: list[PluginState], plugin_filter: str = "") -> str:
    state_map = {state.name: state for state in states}
    groups: dict[str, list[str]] = {}
    title_map: dict[str, str] = {}
    plugin_filter = (plugin_filter or "").strip().lower()
    for spec in specs:
        plugin_name = spec.plugin
        state = state_map.get(plugin_name)
        display = spec.plugin_display or (state.display_name if state else plugin_name)
        desc = spec.plugin_description or (state.description if state else "")
        if plugin_filter and plugin_filter not in {plugin_name.lower(), display.lower()}:
            continue
        title_map[plugin_name] = f"{display}" + (f" · {escape(desc)}" if desc else "")
        groups.setdefault(plugin_name, []).append(f"<code>{escape(prefix)}{escape(spec.usage)}</code> · {escape(spec.summary)}")

    if plugin_filter and not groups:
        return panel("帮助面板", [section("结果", [f"· <i>没有找到插件 {escape(plugin_filter)} 或它没有注册任何命令。</i>"])])

    sections = []
    for plugin_name in sorted(groups.keys()):
        sections.append(section(title_map.get(plugin_name, plugin_name), groups[plugin_name]))
    sections.append(
        section(
            "交互说明",
            [
                "· -help 会按已注册插件自动生成，不需要手写维护",
                "· 轻命令直接回复；重任务先受理再后台回包",
                "· 新增插件后，重载插件或重启服务即可接入新命令",
            ],
        )
    )
    footer = "<i>发送 <code>{0}plugins</code> 可查看插件运行状态；发送 <code>{0}help 插件名</code> 可只看某个插件的命令。</i>".format(escape(prefix))
    return panel("TG-Radar 插件帮助", sections, footer)


def render_job_accept_panel(command: str, trace: str, job_id: int | None, detail: str) -> str:
    rows = [bullet("命令", command, code=False), bullet("跟踪号", trace, code=False), bullet("说明", detail, code=False)]
    if job_id is not None:
        rows.insert(1, bullet("任务 ID", job_id))
    return panel("后台任务已受理", [section("调度状态", rows)], "<i>该任务已进入后台执行；不会阻塞 help / status / folders 这类轻命令。</i>")


def render_plugins_panel(admin_states: list[PluginState], core_states: list[dict[str, str]], prefix: str) -> str:
    admin_rows = []
    for state in admin_states:
        admin_rows.append(
            "\n".join(
                [
                    f"<b>{escape(state.display_name)}</b>",
                    bullet("插件名", state.name, code=False),
                    bullet("来源", state.source, code=False),
                    bullet("版本", state.version, code=False),
                    bullet("状态", state.status, code=False),
                    bullet("健康", state.health_status + (f" · {state.health_summary}" if state.health_summary else ""), code=False),
                    bullet("命令数", len(state.commands)),
                    bullet("命令", ", ".join(state.commands) if state.commands else "无", code=False),
                ]
            )
        )
    if not admin_rows:
        admin_rows = ["· <i>当前没有已加载的 Admin 插件。</i>"]

    core_rows = []
    for item in core_states:
        core_rows.append(
            "\n".join(
                [
                    f"<b>{escape(item['display_name'])}</b>",
                    bullet("插件名", item["name"], code=False),
                    bullet("版本", item["version"], code=False),
                    bullet("运行状态", item["status"] or "unknown", code=False),
                    bullet("摘要", item["summary"] or "未上报", code=False),
                    bullet("监听目标", item["chats"] or "0", code=False),
                    bullet("规则数", item["rules"] or "0", code=False),
                    bullet("最近重载", item["last_reload"] or "未记录", code=False),
                ]
            )
        )
    if not core_rows:
        core_rows = ["· <i>当前没有发现 Core 插件元数据。</i>"]

    return panel(
        "插件运行状态",
        [section("Admin 插件", admin_rows), section("Core 插件", core_rows)],
        "<i>发送 <code>{0}pluginreload</code> 可重载 Admin 插件；修改 Core 插件后建议执行 <code>{0}restart</code>。</i>".format(escape(prefix)),
    )
