# TG-Radar 本轮稳定性修复说明

## 这轮重点

1. 去掉了依赖短周期 `revision` 轮询才能生效的老思路，改成 **事件驱动热更新**。
2. 修复了 **Telegram 命令偶发没反应 / 没监听到** 的高风险入口问题。
3. 优化了 Admin 内部调度，让命令响应和后台任务更顺滑。
4. 保留现有功能逻辑，不再要求频繁重启或依赖 3 秒检查一次的方式。

## 本轮关键改动

### 1. Core 热更新改成事件驱动
- Admin 在这些场景下会直接下发 `reload_core`：
  - `-enable`
  - `-disable`
  - `-addrule`
  - `-delrule`
  - `-setalert`
  - 自动同步发现分组/缓存变化
- Core 通过 `SIGUSR1` 收到重载信号后立即刷新目标映射和规则。
- `revision_poll_seconds` 现在默认改为 `0`，表示 **关闭短周期轮询**。
- 仍然保留可选兜底轮询：如果你手动把 `revision_poll_seconds` 设成大于 0，就会开启低频 fallback watcher。

### 2. 修复 Telegram 命令没响应
旧版本命令监听入口依赖：
- `events.NewMessage(chats=["me"], pattern=...)`

这会在部分 Telethon / Saved Messages 环境里出现：
- 服务正常
- Linux 状态正常
- 但 Telegram 命令根本没进 handler

现在改成：
- 先监听所有 `NewMessage`
- 再在函数里手动判断：
  - 是否是自己的消息
  - 是否在 Saved Messages / 自己对自己私聊
  - 是否以当前命令前缀开头
- 并补了命令接收日志 `COMMAND_RX`

### 3. 调度层更顺滑
- `CommandBus` 新增 notifier
- `AdminScheduler` 新增 `wakeup` 事件
- 新任务入队后会立即唤醒调度层，不再完全依赖定时轮询去发现新任务
- 这样 `sync / reload_core / update / restart / snapshot flush` 的排队体感更顺畅

### 4. 避免不必要的脏逻辑
- `addroute` 不再偷偷给新分组塞演示监控规则
- `config.example.json` 和 `config.schema.json` 已同步把 `revision_poll_seconds` 改成 0，并说明事件驱动策略

## 当前推荐配置

```json
"sync_interval_seconds": 1800,
"revision_poll_seconds": 0,
"scheduler_poll_seconds": 1,
"snapshot_flush_debounce_seconds": 3
```

如果你想保留低频兜底轮询，可以把：

```json
"revision_poll_seconds": 300
```

表示：
- 平时主要靠事件驱动立即重载
- 每 5 分钟再做一次低频兜底检查

## 本轮修复的核心结论

### 关键词监控
- 继续由 Core 独立处理
- 不再依赖 Admin 轮询才能吃到规则变化
- 正常情况下应比旧版更接近实时

### Telegram 命令
- 旧版“服务正常但没反应”的高风险监听写法已经替换
- 现在收到命令会先进入 handler，再由 Admin 调度层处理

### 热更新
- 不再强依赖短周期 3 秒轮询
- 改成 **配置变更 → Admin 发信号 → Core 立即重载**

## 仍需你上机重点验证的两项

1. 在 Saved Messages 连续测试：
   - `-help`
   - `-status`
   - `-sync`
   - `-addrule`
   - `-delrule`

2. 在监控群发关键词测试：
   - 看告警是否实时
   - 看改规则后是否无需重启就生效
