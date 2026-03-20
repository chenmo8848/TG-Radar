# Runtime Directory

`runtime/` 只用于保存运行时数据，不属于源码的一部分。

运行过程中会生成或更新：
- `logs/`
- `sessions/`
- `backups/`
- `radar.db`
- `radar.db-wal`
- `radar.db-shm`

不要把真实日志、session 或数据库提交到 GitHub。
