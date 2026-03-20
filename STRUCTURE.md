# TG-Radar 目录结构

- `install.sh`：一键安装入口，兼容本地执行与 `bash <(curl ...)` 远程执行
- `deploy.sh`：`TR` 终端控制入口，负责服务管理、更新、重授权、自检、卸载
- `config.example.json`：带中文说明的配置模板
- `src/`：Python 源码入口
- `src/tgr/`：核心模块（配置、数据库、同步逻辑、管理层、监听层）
- `runtime/`：运行时目录（日志、session、数据库、备份）
- `scripts/cleanup_legacy.sh`：旧版残留清理脚本
