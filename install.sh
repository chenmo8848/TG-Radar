#!/bin/bash
# ============================================================
# TG-Radar -- 核心一键安装向导 (Pure Asyncio Version)
# ============================================================
set -euo pipefail

REPO="chenmo8848/TG-Radar"
INSTALL_DIR="/root/TG-Radar"
GLOBAL_CMD="/usr/local/bin/TGR"
COMMIT_FILE="$INSTALL_DIR/.commit_sha"

# 现代 CLI 色彩
B='\033[1m'
DIM='\033[2m'
RES='\033[0m'
MAIN='\033[36m'
TAG_OK='\033[42;30m'
TAG_ERR='\033[41;37m'
TAG_WARN='\033[43;30m'

echo -e "\n${MAIN}${B} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ${RES}"
echo -e "${B}                 TG-RADAR 态势感知系统 · 安装向导                 ${RES}"
echo -e "${MAIN}${B} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ${RES}\n"

if [ "$(id -u)" -ne 0 ]; then 
    echo -e "  ${TAG_ERR} 警告 ${RES} 需要 root 权限运行此脚本。"
    exit 1
fi

echo -ne "  ${MAIN}⠋${RES} 正在检查底层环境依赖..."
for cmd in curl unzip python3; do 
    if ! command -v "$cmd" > /dev/null 2>&1; then
        echo -e "\n  ${TAG_ERR} 错误 ${RES} 缺少必要依赖工具：$cmd"
        exit 1
    fi
done
echo -e "\r  ${TAG_OK} 环境 ${RES} 基础依赖检查通过       "

echo -ne "  ${MAIN}⠋${RES} 正在向云端寻址最新核心固件..."
API_RES=$(curl -fsSL --connect-timeout 5 "https://api.github.com/repos/${REPO}/commits/main") || { 
    echo -e "\n  ${TAG_ERR} 错误 ${RES} 无法访问 GitHub API，请检查服务器网络。"
    exit 1
}
LATEST_SHA=$(echo "$API_RES" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)

if [ -z "$LATEST_SHA" ]; then 
    echo -e "\n  ${TAG_ERR} 错误 ${RES} 无法解析最新 Commit 节点。"
    exit 1
fi
SHORT_SHA=${LATEST_SHA:0:7}
echo -e "\r  ${TAG_OK} 寻址 ${RES} 锁定代码节点 [${SHORT_SHA}]"

RESTORE_CONFIG=false
if [ -f "$INSTALL_DIR/config.json" ]; then
    cp "$INSTALL_DIR/config.json" /tmp/tg_radar_config.bak
    echo -e "  ${TAG_WARN} 继承 ${RES} 检测到历史配置，已自动执行安全备份。"
    RESTORE_CONFIG=true
fi

echo -ne "  ${MAIN}⠋${RES} 正在拉取并挂载原生引擎架构..."
mkdir -p "$INSTALL_DIR"
rm -rf /tmp/tgr_main.zip /tmp/TG-Radar-main
curl -fsSL "https://github.com/${REPO}/archive/refs/heads/main.zip" -o /tmp/tgr_main.zip || { 
    echo -e "\n  ${TAG_ERR} 错误 ${RES} 数据包流转失败。"
    exit 1
}

unzip -q -o /tmp/tgr_main.zip -d /tmp/ >/dev/null 2>&1
# 强制覆写代码，但保留 session 文件
cp -af /tmp/TG-Radar-main/. "$INSTALL_DIR/"
rm -rf /tmp/tgr_main.zip /tmp/TG-Radar-main
echo -e "\r  ${TAG_OK} 挂载 ${RES} 核心引擎文件覆写完成     "

# 还原配置
if [ "$RESTORE_CONFIG" = true ]; then 
    cp /tmp/tg_radar_config.bak "$INSTALL_DIR/config.json"
    rm -f /tmp/tg_radar_config.bak
fi

# 写入 Commit Hash 用于 OTA 固件更新比对
echo "$LATEST_SHA" > "$COMMIT_FILE"

chmod +x "$INSTALL_DIR/deploy.sh" "$INSTALL_DIR/install.sh" 2>/dev/null || true

# 注册全局命令
echo -ne "  ${MAIN}⠋${RES} 正在封装全局环境变量..."
cat > "$GLOBAL_CMD" << 'TGREOF'
#!/bin/bash
exec bash /root/TG-Radar/deploy.sh "$@"
TGREOF
chmod +x "$GLOBAL_CMD"
echo -e "\r  ${TAG_OK} 封装 ${RES} TGR 全局快捷指令注册完毕 "

echo -e "\n  ${TAG_OK} 成功 ${RES} ${B}TG-Radar 核心框架安装就绪！${RES}"
echo -e "         正在唤起系统级部署管家 (2 秒后)...\n"
sleep 2
exec bash "$INSTALL_DIR/deploy.sh"
