from __future__ import annotations

from ...services.panels import render_plugins_panel
from ...telegram_utils import panel, section

PLUGIN_META = {
    "name": "plugins",
    "display_name": "插件管理",
    "version": "1.0.0",
    "description": "插件状态查看与 Admin 插件热重载。",
    "mode": "admin",
    "api_version": "1",
}


def register(registry) -> None:
    @registry.command("plugins", summary="查看插件运行状态", usage="plugins", category="general", plugin="plugins")
    async def plugins_cmd(ctx):
        await ctx.app.plugin_manager.refresh_admin_health(ctx.app)
        runtime = ctx.app.db.get_runtime_stats()
        text = render_plugins_panel(ctx.app.plugin_manager.admin_states, ctx.app.plugin_manager.core_runtime_snapshot(runtime), ctx.app.config.cmd_prefix)
        await ctx.app.reply_panel(ctx.event, text, auto_delete=0)

    @registry.command("pluginreload", summary="重载 Admin 插件并刷新命令表", usage="pluginreload", category="general", plugin="plugins")
    async def pluginreload_cmd(ctx):
        await ctx.app.reload_admin_plugins()
        await ctx.app.reply_panel(
            ctx.event,
            panel("Admin 插件已重载", [section("结果", ["· 命令表已根据当前插件重新生成。", "· Core 插件修改后仍建议执行 restart 重新拉起 Core。"])]),
            auto_delete=0,
        )
