# TG-Radar

以第一版为唯一功能基线重构的 **TR 管理器**。

目标：

- 功能不丢
- 插件全解耦
- 核心仓库与插件仓库分离
- 一键安装
- Linux 终端统一用 `TR`
- Telegram 收藏夹统一用命令前缀 `-`
- 全部文案统一为 **TR 管理器** 口径

## 架构

- `TG-Radar`：核心仓库
  - Telegram 适配层
  - 命令注册中心
  - 插件管理器
  - 任务总线
  - 数据库与配置
  - 安装 / 部署 / 更新 / 自检
- `TG-Radar-Plugins`：插件仓库
  - `plugins/admin/`：Telegram 收藏夹命令插件
  - `plugins/core/`：Core 实时监听插件

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

安装器会自动完成：

1. 拉取核心仓库
2. 拉取插件仓库到 `/root/TG-Radar/plugins-external/TG-Radar-Plugins`
3. 创建 Python 虚拟环境
4. 安装核心与插件依赖
5. 写入 `config.json`
6. 首次 Telegram 授权
7. 首次同步
8. 注册并启动 systemd 双服务
9. 注册终端命令 `TR`

## Linux 终端管理

```bash
TR
TR status
TR doctor
TR sync
TR reauth
TR logs admin
TR logs core
TR update
```

## Telegram 收藏夹控制

```text
-help
-status
-folders
-rules 示例分组
-enable 示例分组
-addrule 示例分组 规则A 监控词A 监控词B
-setrule 示例分组 规则A 新表达式
-delrule 示例分组 规则A
-delrule 示例分组 规则A 监控词A
-addroute 示例分组 标题词A 标题词B
-routescan
-jobs
-sync
-update
-restart
-plugins
-pluginreload
```

## 目录

```text
/root/TG-Radar
├── install.sh
├── deploy.sh
├── config.example.json
├── config.schema.json
├── plugins-external/
│   └── TG-Radar-Plugins
├── runtime/
└── src/
    ├── radar_admin.py
    ├── radar_core.py
    ├── bootstrap_session.py
    ├── sync_once.py
    └── tgr/
        ├── admin_service.py
        ├── core_service.py
        ├── config.py
        ├── db.py
        ├── scheduler.py
        ├── sync_logic.py
        └── core/
            └── plugin_system.py
```
