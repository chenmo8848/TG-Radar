from __future__ import annotations

import shlex

from ...services.panels import render_help_panel


def register(registry) -> None:
    @registry.command('help', summary='查看全部命令帮助', usage='help', category='general', plugin='admin.general')
    async def help_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, render_help_panel(ctx.app.config.cmd_prefix, registry.unique_specs()), auto_delete=0)

    @registry.command('ping', summary='检查前台是否在线', usage='ping', category='general', plugin='admin.general')
    async def ping_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, ctx.app.render_ping_message(), auto_delete=0)

    @registry.command('status', summary='查看总体运行状态', usage='status', category='general', plugin='admin.general')
    async def status_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, ctx.app.render_status_message(), auto_delete=0)

    @registry.command('config', summary='查看关键配置', usage='config', category='general', plugin='admin.general')
    async def config_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, ctx.app.render_config_message(), auto_delete=0)

    @registry.command('version', summary='查看版本与架构信息', usage='version', category='general', plugin='admin.general')
    async def version_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, ctx.app.render_version_message(), auto_delete=0)

    @registry.command('jobs', summary='查看后台任务队列', usage='jobs', category='general', plugin='admin.general')
    async def jobs_cmd(ctx):
        await ctx.app.reply_panel(ctx.event, ctx.app.render_jobs_message(), auto_delete=0)

    @registry.command('log', summary='查看最近关键日志', usage='log [important|normal|all] [20]', category='general', plugin='admin.general')
    async def log_cmd(ctx):
        scope = 'important'
        limit = 15
        try:
            tokens = shlex.split(ctx.args) if ctx.args else []
        except Exception:
            tokens = [part for part in (ctx.args or '').split() if part]
        for token in tokens:
            low = token.lower()
            if low in {'all', 'raw', 'full', 'debug'}:
                scope = 'all'
            elif low in {'normal', 'recent'}:
                scope = 'normal'
            elif low in {'important', 'key'}:
                scope = 'important'
            elif token.isdigit():
                limit = max(1, min(40, int(token)))
        await ctx.app.reply_panel(ctx.event, ctx.app.render_log_message(limit=limit, scope=scope), auto_delete=0)
