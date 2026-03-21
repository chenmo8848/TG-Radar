# TG-Radar 4.0.1 修复说明

## 这次重点修复

1. **Saved Messages 判定热路径改造**
   - 先用本地 `chat_id/sender_id/self_id` 秒判。
   - 只有本地判定失败时，才退回 `event.get_chat()`。
   - 退回查询加了 `1.2s` 超时，避免轻命令卡死在 Telethon 实体查询上。

2. **命令热路径日志去阻塞**
   - 新增 `RadarDB.try_log_event()`。
   - `CMD_SEEN / CMD_DROP / CMD_ACCEPTED / CMD_ACK / COMMAND` 改为短超时 best-effort 写入。
   - 避免 SQLite 写锁竞争时把 `-help / -ping / -status / -jobs` 拖成几十秒甚至几分钟。

3. **轻命令不再优先 edit 原消息**
   - `help / ping / status / version / config / log / folders / rules / routes / jobs / 未知命令` 默认独立回复。
   - 不再强依赖原消息编辑链路。

4. **编辑失败兜底**
   - `quick_ack()` 编辑失败后会自动 fallback 为回复消息。
   - `edit_message_by_id()` 编辑失败后会 fallback 为回复消息。
   - 避免“后台任务执行完了，但结果没展示出来”。

5. **启动顺序修复**
   - 取消 `AdminApp.__init__()` 里过早写回 `config.json` 快照。
   - 改为启动后按需执行一次分组/群组缓存校准，再写快照，再发启动通知。

6. **统计与文案统一**
   - 新增统一分组统计口径。
   - 启动通知、`-status`、`-folders`、同步完成面板都统一展示：
     - 分组总数
     - 已启用分组
     - 群组总量
     - 启用分组群量
     - 规则总量
     - 生效规则
     - 实际监听目标
     - 自动收纳规则

## 主要修改文件

- `src/tgr/admin_service.py`
- `src/tgr/db.py`
- `src/tgr/version.py`

## 版本

- 原版：`4.0.0`
- 修复版：`4.0.1`
