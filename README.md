# TG-Radar

> Telegram 关键词监听雷达 — 手机在手，天下我有

实时监控 Telegram 群组和频道的关键词，命中即推送告警。  
选项 1 一条龙完成全部初始化（环境 + 配置 + 授权），之后所有管理操作均可在手机 Telegram 中完成，无需再 SSH 登录服务器。

---

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

> 需要 root 权限。安装完成后自动注册全局命令 `TGR`，直接输入 `TGR` 即可打开管理菜单。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `install.sh` | 一键安装脚本，从 GitHub 自动拉取最新 Release 解压部署 |
| `tg_monitor.py` | 核心守护进程，24小时运行，实时监听消息 + 响应 ChatOps 指令 |
| `sync_engine.py` | 同步引擎，从 Telegram 云端拉取分组结构，按需/定时运行 |
| `config.json` | 唯一配置文件，存储 API 凭证、分组规则、系统缓存 |
| `deploy.sh` | 管理菜单脚本，注册为全局命令 `TGR` |

---

## 快速开始

**第一步 — 安装**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

安装完成后自动打开管理菜单。

**第二步 — 一键部署（选项 1）**

在管理菜单中选择 `1) 部署 / 更新`，向导将自动完成：

- 安装系统依赖 & 配置 Python 环境
- 注册 systemd 服务 & 定时同步任务
- **引导填写 config.json**（api\_id / api\_hash / 频道 ID）
- **Telegram 账号授权登录 & 拉取分组**
- 启动监控守护进程

全程有进度提示和结果验证，完成即可使用。

**第三步 — 手机管理**

部署完成后，向 Telegram **Saved Messages** 发送指令即可远程管理：

```
-help      查看全部指令
-folders   查看已同步的分组列表
-enable    启用分组监控
-sync      立即同步分组
-status    查看运行状态
```

---

## 管理菜单

```bash
TGR
```

```
╔══════════════════════════════════════════════════════╗
║   TG-Radar  --  Telegram 关键词监听雷达  v4.0.3     ║
╚══════════════════════════════════════════════════════╝

服务状态：● 运行中
配置文件：● 已填写
全局命令：● TGR 已注册

请选择操作：

1)  部署 / 更新          ← 全程一条龙：环境 + 配置 + 授权
2)  停止服务
3)  启动服务
4)  重启服务
5)  查看状态与日志
6)  首次授权向导         ← 仅重新授权/同步时使用
7)  完全卸载
8)  退出
```

---

## ChatOps 指令速查

默认前缀 `-`，可在 `config.json` 的 `cmd_prefix` 字段修改为 `!` 或 `.` 等。

**查询类**

| 指令 | 说明 |
|---|---|
| `-help` | 显示全部指令 |
| `-ping` | 心跳检测，返回在线时长和累计命中次数 |
| `-status` | 完整状态报告 |
| `-log [行数]` | 系统日志，默认 20 行，最多 100 |
| `-folders` | 所有分组概览（状态/群数/规则数/频道） |
| `-rules <分组名>` | 指定分组的规则详情 |

**配置类**（写入 config.json，自动重启生效）

| 指令 | 说明 |
|---|---|
| `-enable <分组名>` | 启用分组监控 |
| `-disable <分组名>` | 关闭分组监控 |
| `-setalert <分组名>\|<频道ID>` | 设置分组专属告警频道 |
| `-setglobal <频道ID>` | 设置全局告警频道 |
| `-addrule <分组名>\|<规则名>\|<正则>` | 新增关键词规则 |
| `-delrule <分组名>\|<规则名>` | 删除规则 |

**系统类**

| 指令 | 说明 |
|---|---|
| `-sync` | 触发云端分组同步 |
| `-restart` | 重启监控服务 |

> 分组名支持模糊匹配（大小写不敏感、子串匹配），打错也能识别。

---

## 配置说明

```jsonc
{
    "api_id": 1234567,                     // 从 my.telegram.org 获取
    "api_hash": "your_api_hash",           // 从 my.telegram.org 获取
    "global_alert_channel_id": -100xxxxxx, // 全局告警推送频道 ID
    "notify_channel_id": null,             // 系统通知频道，null 则使用全局频道
    "cmd_prefix": "-"                      // 指令前缀，可改为 "!" 或 "."
}
```

---

## 安装路径

```
/root/TG-Radar/
├── tg_monitor.py          核心守护进程
├── sync_engine.py         同步引擎
├── config.json            配置文件
├── deploy.sh              管理脚本
├── TG_Radar_session.*     Telegram session（自动生成）
└── venv/                  Python 虚拟环境（自动生成）

/usr/local/bin/TGR                         全局命令（自动注册）
/etc/systemd/system/tg_monitor.service     系统服务（自动注册）
```

---

## 系统要求

- Linux（推荐 Ubuntu 20.04+），root 权限
- Python 3.10+
- Telegram 账号
- API 凭证（[my.telegram.org](https://my.telegram.org) → API development tools）

---

## 卸载

```bash
TGR
# 选择 7) 完全卸载
```

可选是否同时删除 `/root/TG-Radar/` 目录。保留目录则下次重新部署时配置不丢失。

---

## License

MIT
