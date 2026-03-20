# TG-Radar 交付说明

## 本次完成内容

### 1. 项目口径统一
- 项目名统一为 **TG-Radar**
- 终端命令统一为 **TR**
- 默认部署目录统一为 **`/root/TG-Radar`**

### 2. Linux 端文案升级
- 安装向导文案全面重写
- `TR` 菜单、自检、卸载、更新、日志查看文案统一
- `bootstrap_session.py` / `sync_once.py` 的终端提示重写

### 3. Telegram 交互升级
- `help / status / config / sync / update / restart` 面板重新排版
- 更适合 Telegram 气泡宽度：短标题、短行、分块展示
- 保留优先编辑原命令消息与自动回收策略
- fallback 回复会自动清理原始命令消息

### 4. 告警通知升级
- 改为 **同一目标聚合告警**
- 同一条消息中相同关键词重复出现时，会统计频次并在告警面板展示
- 同时命中多条规则时，会在同一张告警卡片中汇总
- 保留原消息直达链接

### 5. 配置与说明升级
- `config.example.json` 改为带中文说明的模板
- `config.py` 回写 `config.json` 时同步附带中文说明
- `runtime/README.md`、`STRUCTURE.md` 一并整理

## 已确认事项
- 项目名称与命令口径已统一为 `TG-Radar / TR`
- Telegram 交互与终端文案已整体升级
- README 已按当前脚本能力重新收尾

## 仍需你在线环境验证的部分
- 首次 Telegram 登录授权
- 真实账号下的分组同步与路由补群
- 真实消息流触发的告警投递
