# TG-Radar

TG-Radar 是一个面向 Telegram 的关键词监控与分组路由系统，采用 **核心仓库 + 外部插件仓库** 的结构：

- 核心仓库：`TG-Radar`
- 插件仓库：`TG-Radar-Plugins`

默认部署目录：

```text
/root/TG-Radar
/root/TG-Radar/plugins-external/TG-Radar-Plugins
```

## 当前版本重点

- 轻命令直接回复：`-help`、`-ping`、`-status`、`-folders`、`-jobs`、`-log`
- 重命令进入任务总线：`-sync`、`-routescan`、`-update`、`-restart`
- 命令系统走注册中心，`-help` 由已注册插件命令自动生成
- Core 关键词监控走独立插件，不再把监控逻辑硬塞进总控文件
- 默认插件仓库放在核心目录内部：`./plugins-external/TG-Radar-Plugins`
- `install.sh` 现在是一键安装：自动拉插件仓库、授权登录、首次同步、部署 systemd

## 目录

```text
src/tgr/app                命令注册与路由
src/tgr/builtin_plugins    核心内建插件
src/tgr/services           消息发送、面板格式化
src/tgr/plugin_manager.py  插件发现/加载/健康状态
src/tgr/core_service.py    Core 运行时
src/tgr/admin_service.py   Admin 运行时
plugins-external/          外部插件仓库安装位置
scripts/doctor.sh          环境检查
update.sh                  核心 + 插件一键更新
```

## 一键安装

```bash
cd /root && \
rm -rf /root/TG-Radar && \
git clone https://github.com/chenmo8848/TG-Radar.git /root/TG-Radar && \
cd /root/TG-Radar && \
bash install.sh
```

`install.sh` 会完成：

1. 创建 `.venv`
2. 安装核心依赖
3. 生成或修正 `config.json`
4. 将插件仓库拉到 `/root/TG-Radar/plugins-external/TG-Radar-Plugins`
5. 安装插件依赖
6. 运行 `bootstrap_session.py` 完成 Telegram 授权
7. 运行 `sync_once.py` 完成首次同步
8. 执行 `deploy.sh` 并启动 systemd

如果你不想在安装过程中手输 `api_id` / `api_hash`，可以直接用环境变量：

```bash
cd /root && \
rm -rf /root/TG-Radar && \
git clone https://github.com/chenmo8848/TG-Radar.git /root/TG-Radar && \
cd /root/TG-Radar && \
API_ID=你的API_ID API_HASH=你的API_HASH bash install.sh
```

## 更新

```bash
cd /root/TG-Radar && bash update.sh
```

这会同时：

- 更新核心仓库
- 更新插件仓库
- 安装新增依赖
- 重新同步
- 重启服务

## 诊断

```bash
cd /root/TG-Radar && bash scripts/doctor.sh
```
