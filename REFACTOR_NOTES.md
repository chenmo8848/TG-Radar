# REFACTOR_NOTES

## 本次重构重点

1. **命令系统插件化**
   - 不再把所有 Telegram 命令堆在一个 `admin_service.py` 的 `dispatch()` 里。
   - 通过 `CommandRegistry` + `plugins/admin/*.py` 注册命令。

2. **轻命令 / 重任务分流**
   - 轻命令直接回复。
   - 重任务统一进入 `CommandBus` 和 `AdminScheduler`。

3. **关键词监控独立成插件**
   - `plugins/core/keyword_monitor.py` 独立承担命中逻辑、告警渲染和运行时热重载状态。

4. **启动期先校准再通知**
   - Admin 启动时按需先同步分组与群组缓存，再发启动通知。

5. **去掉“编辑原命令消息”作为默认交互**
   - 除重启恢复消息外，默认改为独立回复，降低 Telegram 编辑失败造成的卡顿感。

## 哪些模块应该优先改

### 关键词监控有 bug
改：
- `src/tgr/plugins/core/keyword_monitor.py`
- 必要时 `src/tgr/core_service.py`

### 自动归纳有 bug
改：
- `src/tgr/plugins/admin/routes.py`
- `src/tgr/sync_logic.py`

### 轻命令响应有 bug
改：
- `src/tgr/plugins/admin/general.py`
- `src/tgr/services/message_io.py`
- `src/tgr/admin_service.py`

### 规则管理有 bug
改：
- `src/tgr/plugins/admin/rules.py`

### 分组开关有 bug
改：
- `src/tgr/plugins/admin/folders.py`

## 兼容边界

这版尽量沿用了原仓库的：
- DB schema
- session 文件命名
- install.sh / deploy.sh / bootstrap_session.py 链路
- sync_logic / scheduler / executors 的总体职责

因此对现有部署方式的冲击比“全新项目重写”小很多。
