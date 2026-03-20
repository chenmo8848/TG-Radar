<img src="https://capsule-render.vercel.app/api?type=rounded&height=220&color=0:EDEDED,45:CBD5E1,100:64748B&text=TG-Radar&fontSize=50&fontColor=111827&fontAlignY=40&desc=Modern%20Telegram%20Radar%20for%20Sync%20Routing%20and%20Live%20Monitoring&descAlignY=63" width="100%" />

<div align="center">

<img src="https://readme-typing-svg.herokuapp.com?font=Inter&weight=600&size=20&duration=2800&pause=700&color=111827&center=true&vCenter=true&width=920&lines=Plan+C+%E6%9E%B6%E6%9E%84+%C2%B7+Admin%2FCore+%E5%8F%8C%E6%9C%8D%E5%8A%A1+%C2%B7+SQLite+WAL;%E8%87%AA%E5%8A%A8%E5%90%8C%E6%AD%A5+%C2%B7+%E7%83%AD%E6%9B%B4%E6%96%B0+%C2%B7+Saved+Messages+ChatOps;%E7%BC%96%E8%BE%91%E5%8E%9F%E6%B6%88%E6%81%AF+%2B+%E5%9E%83%E5%9C%BE%E6%B6%88%E6%81%AF%E8%87%AA%E5%8A%A8%E5%9B%9E%E6%94%B6;%E4%B8%80%E6%9D%A1%E5%91%BD%E4%BB%A4%E9%83%A8%E7%BD%B2%E5%88%B0+%2Froot%2FTG-Radar" alt="typing" />

<p>
  <img src="https://img.shields.io/badge/Architecture-Admin%20%2B%20Core-111827?style=for-the-badge" alt="Architecture" />
  <img src="https://img.shields.io/badge/Storage-SQLite%20WAL-334155?style=for-the-badge" alt="Storage" />
  <img src="https://img.shields.io/badge/Command-TR-475569?style=for-the-badge" alt="TR" />
  <img src="https://img.shields.io/badge/Deploy-/root/TG--Radar-64748B?style=for-the-badge" alt="Deploy" />
</p>

</div>

---

## 项目定位

**TG-Radar** 是一套面向 Telegram 个人号场景的现代化雷达系统，重点解决三件事：

- **Telegram 分组拓扑同步**
- **关键词实时监听与热更新**
- **Saved Messages 控制台式交互管理**

这一版保留了原项目的核心实战逻辑，同时把底层重构为更干净的 **Plan C** 结构：

- **Admin Service**：负责同步、交互、自动收纳、更新与重启控制
- **Core Service**：负责实时监听、规则匹配、告警投递
- **SQLite WAL**：负责状态共享、revision 热更新、持久化队列

---

## 核心亮点

<table>
  <tr>
    <td><b>自动同步</b></td>
    <td>支持定时同步 + 手动强制同步 + revision 热更新</td>
  </tr>
  <tr>
    <td><b>Telegram 交互</b></td>
    <td>通过 <code>Saved Messages</code> 完整控制分组、规则、路由、同步、更新、重启</td>
  </tr>
  <tr>
    <td><b>消息体验</b></td>
    <td>优先编辑原命令消息，面板类消息自动回收，减少垃圾消息堆积</td>
  </tr>
  <tr>
    <td><b>自动收纳</b></td>
    <td>基于规则自动匹配群名并排队加入目标 TG 分组</td>
  </tr>
  <tr>
    <td><b>长期运行</b></td>
    <td>systemd 双服务、Rotating 日志、锁文件、SQLite WAL、持久化任务</td>
  </tr>
  <tr>
    <td><b>终端控制</b></td>
    <td>全局命令统一为 <code>TR</code></td>
  </tr>
</table>

---

## 一键安装

> 默认部署目录：**`/root/TG-Radar`**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh)
```

安装向导会自动完成：

1. 系统依赖安装  
2. Python 虚拟环境初始化  
3. `config.json` 生成  
4. Telegram 首次授权  
5. systemd 双服务注册  
6. 首次同步  
7. 服务启动  

---

## 终端控制

部署完成后直接使用：

```bash
TR
TR status
TR doctor
TR sync
TR reauth
TR logs admin
TR logs core
TR update
TR uninstall
```

---

## Telegram 控制台

在 **Saved Messages / 收藏夹** 中发送命令。

默认示例：

```text
-help
-status
-folders
-rules 业务群
-enable 业务群
-addrule 业务群 核心词 苹果 华为
-addroute 业务群 供需 担保
-sync
-update
-restart
```

### 交互特性

- **优先编辑原命令消息**，像 PagerMaid 那样减少控制台刷屏
- 帮助面板、状态面板、同步结果会**自动回收**
- fallback 回复也会自动清理原始命令消息
- 分组启停、规则变更、缓存变动会通过 **revision watcher** 即时生效

---

## 架构概览

```text
Telegram Account
   ├─ Admin Service
   │   ├─ Saved Messages ChatOps
   │   ├─ Folder Sync Engine
   │   ├─ Auto Route Queue
   │   └─ Update / Restart Control
   │
   ├─ SQLite WAL
   │   ├─ folder rules
   │   ├─ system cache
   │   ├─ route queue
   │   └─ runtime stats
   │
   └─ Core Service
       ├─ Live listener
       ├─ Regex matcher
       ├─ Alert dispatcher
       └─ Hot reload watcher
```

---

## 目录结构

```text
TG-Radar/
├─ install.sh
├─ deploy.sh
├─ config.example.json
├─ requirements.txt
├─ DELIVERY_NOTES.md
├─ runtime/
│  └─ README.md
├─ scripts/
│  └─ cleanup_legacy.sh
└─ src/
   ├─ radar_admin.py
   ├─ radar_core.py
   ├─ bootstrap_session.py
   ├─ sync_once.py
   └─ tgr/
      ├─ admin_service.py
      ├─ core_service.py
      ├─ sync_logic.py
      ├─ db.py
      ├─ config.py
      ├─ telegram_utils.py
      └─ ...
```

---

## 本次现代化升级内容

### Linux 端部署体验

- 安装向导文案重写，分阶段展示部署流程
- `TR` 管理终端重新设计，统一命令与输出风格
- 卸载、清理、重授权、自检文案全面统一

### Telegram 交互体验

- `help / status / config / sync / update / restart` 全部重写为更完整的面板
- 自动同步报告增加分组差异、自动收纳、当前规模等信息
- 启动通知增加架构、规模、路由、版本等信息
- 保留并强化了：
  - **编辑现有消息**
  - **垃圾消息自动回收**

### 脚本结构与命名

- 项目名称统一回归 **TG-Radar**
- 全局命令统一为 **TR**
- 默认部署路径统一为 **`/root/TG-Radar`**
- runtime 目录彻底收口，不再把运行时文件散落到仓库外层

---

## 卸载

彻底卸载：

```bash
TR uninstall
```

只卸服务和命令，保留项目目录：

```bash
TR uninstall keep-data
```

清理旧版残留：

```bash
TR cleanup-legacy
```

---

## 说明

- 首次 Telegram 登录仍然需要输入 **手机号 / 验证码 / 二步密码（如已开启）**
- `runtime/` 中的日志、session、数据库文件都属于运行时数据，不建议提交到 GitHub
- 上传仓库时请保留 `runtime/README.md`，不要提交真实 session 与数据库

---

## 设计目标

这一版的目标不是只“能跑”，而是同时做到：

- **极简**：目录干净、入口明确
- **现代**：视觉、文案、命令界面统一
- **高级**：终端与 Telegram 面板都更像成熟项目
- **专业**：保留原实战逻辑，不做花架子式阉割重构

