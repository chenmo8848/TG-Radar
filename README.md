<div align="center">

<img src="https://capsule-render.vercel.app/api?type=rounded&height=220&color=0:F5F7FA,45:DCE3EB,100:6B7280&text=TG-Radar&fontSize=48&fontColor=111827&fontAlignY=40&desc=Elegant%20Telegram%20Keyword%20Intelligence%20for%20Folder-Based%20Monitoring&descAlignY=63" width="100%" />

<br />

<img src="https://readme-typing-svg.herokuapp.com?font=Inter&weight=600&size=20&pause=2200&color=6B7280&center=true&vCenter=true&width=900&lines=Folder-aware+Telegram+monitoring;Command-driven+rule+management;Auto+sync+%2B+auto+route+%2B+hot+reload;Minimal+surface%2C+serious+control" alt="Typing SVG" />

<br />
<br />

<p>
  <img src="https://img.shields.io/badge/Platform-Linux%20Server-111827?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Runtime-Python%203%20%2B%20Telethon-374151?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Control-Telegram%20Saved%20Messages-4B5563?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Mode-Systemd%20Service-6B7280?style=for-the-badge" />
</p>

</div>

---

## Overview

**TG-Radar** 是一套以 **Telegram 分组（Folders）为核心** 的关键词监控系统。它不是单纯的“监听脚本”，而是一套围绕 **分组同步、规则热更新、自动收纳、远程维护** 设计的长期运行方案。

你在 Telegram 客户端里维护分组，它在服务器侧自动同步分组拓扑；你在 **Saved Messages / 收藏夹** 里下发命令，它即时修改规则、执行同步、更新程序、重启服务；一旦命中关键词，系统会把消息快照、来源、规则名、命中词和跳转链接推送到指定频道。

> 这套项目的核心思路很明确：**把复杂维护动作收拢到 Telegram 内完成，把服务端只保留为稳定执行层。**

---

## Why TG-Radar

<table>
<tr>
<td width="50%" valign="top">

### Folder-first
以 Telegram 原生分组为监控边界。不是手填一堆 chat id，而是直接围绕你的 Telegram 使用习惯工作。

</td>
<td width="50%" valign="top">

### ChatOps-native
控制面板不在网页，不在后台，不在 shell。直接在 Telegram 收藏夹里发命令就能完成日常管理。

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Hot Reload
新增规则、删除规则、启停分组、调整自动路由后，配置会即时热生效，无需手工重启。

</td>
<td width="50%" valign="top">

### Long-running Design
内置进程互斥锁、Systemd 服务、定时自同步、后台队列补充任务，适合长期挂机使用。

</td>
</tr>
</table>

---

## Core Capabilities

### 1) Telegram 分组感知同步
- 通过 `sync_engine.py` 读取 Telegram 分组结构
- 自动识别新分组、分组改名、分组删除
- 将分组内的群组/频道映射写入 `_system_cache`
- 支持按需启用某个分组的监控，而不是一把全开

### 2) 关键词监控与精准告警
- 基于 Telethon 异步监听消息流
- 针对启用分组内的群组/频道做正则匹配
- 告警内容包含：命中词、命中规则、来源群、发送者、原始消息快照、消息跳转链接
- 内置单条消息熔断逻辑，避免重复报警

### 3) Telegram 内远程管理
支持在 **Saved Messages** 直接发送命令进行运维：
- 查看状态
- 查看日志
- 开启/关闭分组监控
- 增删监控词
- 管理自动路由
- 强制同步
- 在线更新
- 远程重启

### 4) 自动路由与收纳
- 可根据群名关键词或正则，把符合条件的新群自动归入指定分组
- 当目标分组不存在时，系统可自动创建分组
- 对需要加入的群执行后台排队处理，降低一次性批量操作风险

### 5) 部署与维护一体化
- `install.sh` 负责一键安装与全局命令注册
- `deploy.sh` 提供交互式控制台 `TGR`
- 自动创建 Python 虚拟环境并安装依赖
- 自动注册 Systemd 服务
- 自动检查上游版本并支持保留配置更新

---

## Installation

### One-line install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

安装脚本会自动完成这些动作：
- 校验 `curl`、`unzip`、`python3`
- 拉取最新代码
- 注册全局命令 `TGR`
- 进入部署向导

---

## Quick Start

### 1. 运行安装脚本
安装结束后会自动进入部署面板。

### 2. 填写 Telegram API 凭证
前往 `my.telegram.org` 获取：
- `API_ID`
- `API_HASH`

### 3. 首次登录 Telegram
部署向导会引导完成登录，并读取你的：
- Telegram 分组
- 可选的通知频道

### 4. 选择要监控的分组
选中的分组会写入 `folder_rules`，并默认开启监控。

### 5. 在 Telegram 收藏夹中发送命令
例如：

```text
-help
-status
-folders
```

默认命令前缀是 `-`，可在初始化时修改。

---

## TGR Console

安装完成后，终端中输入：

```bash
TGR
```

即可打开本地控制台。

| 选项 | 作用 |
|---|---|
| `1` | 执行自动部署初始化 |
| `2` | 停止后台进程 |
| `3` | 启动后台进程 |
| `4` | 重启系统并重载配置 |
| `5` | 查看最近日志 |
| `6` | 刷新 Telegram 账号授权 |
| `7` | 卸载并清理环境 |

这部分适合做底层维护；日常规则操作更推荐直接走 Telegram 命令面板。

---

## Telegram Command Surface

以下命令默认在 **Saved Messages / 收藏夹** 中发送。

### System

| 命令 | 说明 |
|---|---|
| `-help` | 显示完整管理菜单 |
| `-ping` | 返回运行时长与命中统计 |
| `-status` | 查看系统状态、分组规模、规则数量、自动路由队列 |
| `-log 30` | 查看最近 N 条业务日志 |
| `-sync` | 强制执行一次全盘同步 |
| `-update` | 拉取最新版代码并热重启 |
| `-restart` | 重启监控服务 |

### Folder Control

| 命令 | 说明 |
|---|---|
| `-folders` | 查看当前分组列表及监控状态 |
| `-rules 分组名` | 查看指定分组下的规则 |
| `-enable 分组名` | 开启某个分组的监控 |
| `-disable 分组名` | 关闭某个分组的监控 |

### Rule Management

| 命令 | 说明 |
|---|---|
| `-addrule 分组名 规则名 关键词1 关键词2` | 向指定规则追加关键词 |
| `-delrule 分组名 规则名 关键词1 关键词2` | 从指定规则中删除关键词 |

示例：

```text
-addrule 业务群 苹果监控 iPhone MacBook iPad
-delrule 业务群 苹果监控 iPad
```

### Auto Route

| 命令 | 说明 |
|---|---|
| `-routes` | 查看自动收纳规则 |
| `-addroute 分组名 群名匹配词` | 配置自动收纳 |
| `-delroute 分组名` | 删除自动收纳规则 |

示例：

```text
-addroute 业务群 供需 担保
```

上面这种写法会自动转成正则，命中群名后把对应群加入指定分组。

---

## Alert Structure

命中关键词后，系统发送的通知会包含：

- 捕获时间
- 命中词汇
- 命中规则名
- 来源分组
- 消息来源群
- 发送人员
- 原始消息快照
- 可点击跳转的消息链接

这让 TG-Radar 更像一个 **Telegram 原生情报雷达**，而不是只会回一行“命中了”的基础通知器。

---

## Auto Sync Strategy

项目不是一次性初始化后就静态运行。

它包含两层持续对齐机制：

### Manual Sync
你可以随时通过：

```text
-sync
```

手动触发一次完整同步。

### Internal Auto Sync
主进程内部还会定时执行环境自检与同步，对齐：
- 分组结构变化
- 自动路由新增结果
- `_system_cache` 更新

这样即使你在 Telegram 客户端里移动群组、修改分组、增加新的自动收纳规则，系统也能持续追上实际状态。

---

## Project Structure

```text
TG-Radar/
├─ install.sh           # 一键安装脚本
├─ deploy.sh            # 本地管理终端 / TGR
├─ tg_monitor.py        # 主监控引擎
├─ sync_engine.py       # 分组拓扑同步引擎
├─ config.example.json  # 配置示例
└─ README.md
```

---

## Configuration

配置文件核心字段：

```json
{
  "api_id": 1234567,
  "api_hash": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "global_alert_channel_id": -100123456789,
  "notify_channel_id": null,
  "cmd_prefix": "-",
  "auto_route_rules": {},
  "folder_rules": {},
  "_system_cache": {}
}
```

### Important Fields

| 字段 | 说明 |
|---|---|
| `api_id` / `api_hash` | Telegram API 凭证 |
| `global_alert_channel_id` | 默认告警频道 |
| `notify_channel_id` | 系统通知频道，不填则回落到默认告警频道 |
| `cmd_prefix` | Telegram 控制命令前缀 |
| `auto_route_rules` | 自动收纳规则 |
| `folder_rules` | 分组监控规则与启用状态 |
| `_system_cache` | 同步引擎维护的分组拓扑缓存 |

> `folder_rules` 和 `_system_cache` 属于系统核心数据层，更推荐通过命令面板维护，而不是手工硬改。

---

## Runtime Design

### Stability-oriented details
- 进程级互斥锁，防止重复启动多个监控实例
- Systemd 接管主进程生命周期
- 更新与重启动作会保留上下文提示
- 日志记录独立写入业务日志文件
- 自动路由采用后台队列缓慢执行，避免过于激进的批量变更

### Observability
- `-status` 用于看全局运行态
- `-log` 用于回看业务级事件日志
- `journalctl -u tg_monitor -f` 用于看服务级输出

---

## Maintenance

### Common paths

```text
/root/TG-Radar/config.json
/root/TG-Radar/TG_Radar_session
/root/TG-Radar/monitor.log
```

### Useful commands

```bash
TGR
journalctl -u tg_monitor -f
systemctl status tg_monitor
systemctl restart tg_monitor
```

---

## Best Use Cases

- 多个 Telegram 分组的长期关键词监控
- 基于群名规则的自动归档与收纳
- 需要在 Telegram 内完成远程规则管理的个人运维场景
- 希望把“监听 + 告警 + 维护 + 更新”整合为单一工作流的长期挂机方案

---

## Notes

- 该项目依赖 Telegram 账号与 API 凭证，部署前请确保账号环境稳定。
- 建议在独立 Linux 服务器中运行，并使用 root 按项目脚本设计完成安装。
- 规则匹配使用正则表达式，复杂模式建议先自行测试。
- 自动路由属于主动调整 Telegram 分组的行为，建议合理控制规则粒度。

---

<div align="center">

### TG-Radar

**Minimal surface. Serious monitoring.**

将分组、规则、同步与运维，收束到同一条 Telegram 工作流里。

</div>
