<div align="center">

# TG-Radar

**Telegram 关键词监控系统**

全解耦插件架构 · 双进程分离 · 事件驱动同步

[![Version](https://img.shields.io/badge/version-6.0.0-blue.svg)](https://github.com/chenmo8848/TG-Radar)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

</div>

---

## 一键部署

```bash
bash <(curl -sL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

> 在全新 VPS (Ubuntu/Debian) 上以 root 执行。脚本自动完成：安装依赖 → 拉取仓库 → 创建环境 → 写入配置 → Telegram 授权 → 首次同步 → 启动服务。

---

## 架构

```
┌─────────────────────────┐    ┌─────────────────────────┐
│      Admin 进程          │    │       Core 进程          │
│                         │    │                         │
│  收藏夹命令 → 插件分发   │    │  全量消息 → 插件钩子     │
│  CommandBus → Scheduler  │    │  规则匹配 → 告警发送     │
│  后台任务 → Executor     │    │                         │
│                         │    │                         │
│  单 TelegramClient      │    │  单 TelegramClient      │
└────────┬────────────────┘    └────────┬────────────────┘
         │                              │
         └──────── SQLite WAL ──────────┘
                  SIGUSR1 信号
```

**Admin** 处理命令交互与后台任务。**Core** 监听消息并发送告警。两个进程通过 SQLite 共享数据，通过 SIGUSR1 信号触发热重载。

---

## 核心设计

| 特性 | 实现 |
|:-----|:-----|
| **单 Client 模型** | Admin 只用一个 TelegramClient，杜绝双客户端竞争 |
| **Plugin SDK** | 插件唯一入口 `from tgr.plugin_sdk import PluginContext` |
| **文件级配置** | 每个插件独立 `configs/name.json`，可编辑可 Git 管理 |
| **事件总线** | `ctx.emit()` / `ctx.on()` 实现插件间通信 |
| **受控边界** | `ctx.db` / `ctx.ui` / `ctx.bus` 白名单方法 |
| **独立日志** | 每个插件 `runtime/logs/plugins/name.log` |
| **错误熔断** | 连续失败 N 次自动停用，`-reload` 恢复 |
| **Session 自愈** | 损坏自动从 Core session 恢复 |
| **并行钩子** | 消息钩子 `asyncio.gather` 并行执行 |
| **懒加载优化** | 关键词匹配先检规则再调 API，99% 消息零开销跳过 |
| **实时同步** | 监听 Telegram 分组变动事件，秒级增量同步 |

---

## 目录结构

```
TG-Radar/
├── config.json               核心配置（仅 10 项基础设施参数）
├── configs/                   插件配置（每个插件一个 JSON）
│   ├── general.json
│   ├── routes.json
│   └── keyword_monitor.json
├── runtime/
│   ├── radar.db               SQLite 数据库
│   ├── sessions/              Telegram session
│   └── logs/
│       ├── admin.log
│       ├── core.log
│       └── plugins/           插件独立日志
├── src/tgr/
│   ├── plugin_sdk.py          ★ 插件唯一 import 入口
│   ├── _plugin_exports.py     受控子接口
│   ├── core/plugin_system.py  插件系统核心
│   ├── admin_service.py       Admin 服务
│   ├── core_service.py        Core 服务
│   ├── config.py              配置系统
│   ├── db.py                  数据层
│   ├── command_bus.py         命令总线
│   ├── scheduler.py           调度器
│   ├── executors.py           任务执行器
│   ├── sync_logic.py          同步引擎
│   └── telegram_utils.py      工具函数
└── plugins-external/          外部插件仓库
```

---

## 核心配置

`config.json` 只保留基础设施参数，所有业务设置由插件各自管理：

```json
{
    "api_id": 1234567,
    "api_hash": "xxx",
    "cmd_prefix": "-",
    "service_name_prefix": "tg-radar",
    "operation_mode": "stable",
    "global_alert_channel_id": null,
    "notify_channel_id": null,
    "repo_url": "...",
    "plugins_repo_url": "...",
    "plugins_dir": "..."
}
```

---

## 插件 SDK

插件通过 `ctx` 访问所有核心服务：

```python
from tgr.plugin_sdk import PluginContext

def setup(ctx: PluginContext):
    @ctx.command("mycommand", summary="描述", usage="mycommand", category="分类")
    async def handler(app, event, args):
        value = ctx.config.get("my_key")
        ctx.log.info("执行命令")
        await ctx.reply(event, ctx.ui.panel("标题", [ctx.ui.section("内容", [...])]))
```

| 接口 | 功能 |
|:-----|:-----|
| `ctx.config` | 读写插件配置 (`configs/name.json`) |
| `ctx.db` | 白名单数据库方法 |
| `ctx.ui` | HTML 渲染工具 |
| `ctx.bus` | 提交后台任务 |
| `ctx.log` | 插件独立日志 |
| `ctx.client` | Telethon 客户端 |
| `ctx.emit / ctx.on` | 事件总线 |
| `ctx.reply` | 统一回复 |

---

## 终端管理

```bash
TR              # 交互菜单
TR status       # 服务状态
TR restart      # 重启双服务
TR logs admin   # Admin 日志
TR logs core    # Core 日志
TR update       # 拉取更新并重启
TR doctor       # 环境自检
TR reauth       # 重新授权
```

## Telegram 命令

在收藏夹发送，默认前缀 `-`：

| 命令 | 功能 |
|:-----|:-----|
| `-help` | 命令列表 |
| `-status` | 系统状态 |
| `-plugins` | 插件状态 |
| `-folders` | 分组列表 |
| `-reload name` | 热重载插件 |
| `-pluginconfig name` | 插件配置 |
| `-sync` | 手动同步 |

---

## 同步机制

三层保障确保分组数据实时：

| 层 | 触发 | 延迟 |
|:---|:-----|:-----|
| **实时** | Telegram 分组变动事件 | 3 秒 |
| **手动** | `-sync` 命令 | 即时 |
| **定时** | 每日自动（可配置） | 最长 24h |

---

## 获取群 ID

从任意群/频道**转发一条消息到收藏夹**，系统自动回复来源群的 ID、类型，以及快捷操作命令。

---

<div align="center">
<sub>Built with Telethon · SQLite WAL · APScheduler</sub>
</div>
