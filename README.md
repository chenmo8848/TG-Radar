# TG-Radar

插件化重构版核心仓库。

## 设计目标

- 核心仓库只保留框架、数据库、Telegram 适配器、任务总线和系统内建插件。
- 业务功能插件放在独立仓库 `TG-Radar-Plugins`。
- `-help` 根据已注册插件和命令自动生成。
- `-plugins` 可查看插件加载与健康状态。
- 轻命令直接回复；重任务后台排队并独立回包。

## 推荐目录

```text
/root/TG-Radar
/root/TG-Radar-Plugins
```

默认 `config.json` 中 `plugins_dir` 为 `../TG-Radar-Plugins`，因此按上面目录放置即可自动发现外部插件。

## 首次安装

```bash
cd /root/TG-Radar
bash install.sh
nano config.json
source .venv/bin/activate
python src/bootstrap_session.py
python src/sync_once.py
./deploy.sh
```

## 关键命令

- `-help`
- `-help 插件名`
- `-plugins`
- `-pluginreload`
- `-status`
- 其余业务命令由外部插件仓库提供

## 插件 API 约定

Admin 插件文件需要提供：

- `PLUGIN_META`
- `register(registry)`
- 可选 `healthcheck(app)`

Core 插件文件需要提供：

- `PLUGIN_META`
- 可选 `on_start(app)`
- 可选 `on_reload(app)`
- 可选 `on_message(app, event)`
- 可选 `healthcheck(app)`
