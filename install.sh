#!/bin/bash
# ============================================================
#  TG-Radar  --  一键安装脚本 v5.1.1 (主分支直连版)
# ============================================================
set -euo pipefail

REPO="chenmo8848/TG-Radar"
INSTALL_DIR="/root/TG-Radar"
GLOBAL_CMD="/usr/local/bin/TGR"
VERSION="v5.1.1"
BOLD='\033[1m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RESET='\033[0m'

echo -e "\n${BOLD}  ============================================================${RESET}"
echo -e "${BOLD}     TG-Radar  --  Telegram 关键词监听雷达  --  安装程序 ${VERSION}      ${RESET}"
echo -e "${BOLD}  ============================================================${RESET}\n"

if [ "$(id -u)" -ne 0 ]; then echo -e "  ${YELLOW}[警告] 需要 root 权限。${RESET}"; exit 1; fi
for cmd in curl unzip python3; do command -v "$cmd" > /dev/null 2>&1 || { echo "  [错误] 缺少工具：$cmd"; exit 1; }; done

RESTORE_CONFIG=false
if [ -f "$INSTALL_DIR/config.json" ]; then
    cp "$INSTALL_DIR/config.json" /tmp/tg_radar_config.bak
    echo -e "  ${YELLOW}[提示] 已备份现有 config.json，安装后将自动还原。${RESET}"
    RESTORE_CONFIG=true
fi

echo -e "  ${CYAN}==>${RESET} 正在从 GitHub 主分支拉取最新核心代码..."
mkdir -p "$INSTALL_DIR"

# 直接下载 main 分支的最新源码压缩包，彻底绕过 Releases 限制
DOWNLOAD_URL="https://github.com/${REPO}/archive/refs/heads/main.zip"
curl -fsSL "$DOWNLOAD_URL" -o /tmp/TG_Radar_main.zip || { echo "  [错误] 源码下载失败。"; exit 1; }

# 解压并覆盖到安装目录
unzip -q -o /tmp/TG_Radar_main.zip -d /tmp/
cp -rf /tmp/TG-Radar-main/* "$INSTALL_DIR/"
rm -rf /tmp/TG_Radar_main.zip /tmp/TG-Radar-main

if [ "$RESTORE_CONFIG" = true ]; then cp /tmp/tg_radar_config.bak "$INSTALL_DIR/config.json" && rm -f /tmp/tg_radar_config.bak; fi
chmod +x "$INSTALL_DIR/deploy.sh"

cat > "$GLOBAL_CMD" << 'TGREOF'
#!/bin/bash
exec bash /root/TG-Radar/deploy.sh "$@"
TGREOF
chmod +x "$GLOBAL_CMD"

echo -e "\n  ${GREEN}[完成]${RESET} TG-Radar ${VERSION} 安装成功！2 秒后自动打开管理菜单...\n"
sleep 2
exec bash "$INSTALL_DIR/deploy.sh"
