PLUGIN_META = {
    "name": "system_panel",
    "version": "5.0.0",
    "description": "TR 管理器系统面板与插件控制命令",
}


async def cmd_help(app, event, args):
    await app.safe_reply(event, app.render_help_message(), auto_delete=0)


async def cmd_plugins(app, event, args):
    await app.plugin_manager.run_healthchecks()
    await app.safe_reply(event, app.render_plugins_message(), auto_delete=0)


async def cmd_pluginreload(app, event, args):
    app.plugin_manager.load_admin_plugins()
    await app.plugin_manager.run_healthchecks()
    await app.safe_reply(event, app.render_plugins_message(), auto_delete=0, prefer_edit=False)


def setup(ctx):
    ctx.register_command("help", cmd_help, summary="查看已注册命令总表", usage="help", category="系统面板")
    ctx.register_command("plugins", cmd_plugins, summary="查看全部插件运行状态", usage="plugins", category="系统面板")
    ctx.register_command("pluginreload", cmd_pluginreload, summary="重新加载 Admin 插件命令表", usage="pluginreload", category="系统面板", heavy=False)
