# TG-Radar 目录结构

- `install.sh`：一键安装入口，支持本地执行和 `bash <(curl ...)` 远程执行
- `deploy.sh`：`TR` 全局控制入口，负责服务管理、更新、卸载、自检
- `config.example.json`：默认配置模板
- `src/`：Python 源码入口
- `src/tgr/`：核心模块（配置、数据库、同步、管理层、监听层）
- `runtime/`：运行时目录（日志、session、数据库、备份）
- `scripts/cleanup_legacy.sh`：旧版残留清理脚本
