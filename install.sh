#!/bin/bash
# ============================================================
# TG-Radar -- 核心一键安装向导 (Enterprise Version)
# ============================================================
set -euo pipefail

REPO="chenmo8848/TG-Radar"
INSTALL_DIR="/root/TG-Radar"
GLOBAL_CMD="/usr/local/bin/TGR"
COMMIT_FILE="$INSTALL_DIR/.commit_sha"

B='\033[1m'
DIM='\033[2m'
RES='\033[0m'
MAIN='\033[36m'
TAG_OK='\033[42;30m'
TAG_ERR='\033[41;37m'
TAG_WARN='\033[43;30m'

echo -e "\n${MAIN}${B} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ${RES}"
echo -e "${B}              TG-Radar 企业级监控系统 · 安装引导               ${RES}"
echo -e "${MAIN}${B} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ${RES}\n"

if [ "$(id -u)" -ne 0 ]; then 
    echo -e "  ${TAG_ERR} 权限提示 ${RES} 当前非 root 账户，请提权后重试。"
    exit 1
fi

echo -ne "  ${MAIN}⠋${RES} 正在校验基础依赖组件..."
for cmd in curl unzip python3; do 
    if ! command -v "$cmd" > /dev/null 2>&1; then
        echo -e "\n  ${TAG_ERR} 组件缺失 ${RES} 无法定位系统依赖：$cmd"
        exit 1
    fi
done
echo -e "\r  ${TAG_OK} 系统 ${RES} 基础环境校验通过       "

echo -ne "  ${MAIN}⠋${RES} 正在获取最新核心代码..."
API_RES=$(curl -fsSL --connect-timeout 5 "https://api.github.com/repos/${REPO}/commits/main") || { 
    echo -e "\n  ${TAG_ERR} 网络异常 ${RES} 无法访问源码仓库，请检查服务器出口网络。"
    exit 1
}
LATEST_SHA=$(echo "$API_RES" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)

if [ -z "$LATEST_SHA" ]; then 
    echo -e "\n  ${TAG_ERR} 校验异常 ${RES} 无法解析远端版本号。"
    exit 1
fi
SHORT_SHA=${LATEST_SHA:0:7}
echo -e "\r  ${TAG_OK} 验证 ${RES} 确认可用版本: [${SHORT_SHA}]"

RESTORE_CONFIG=false
if [ -f "$INSTALL_DIR/config.json" ]; then
    cp "$INSTALL_DIR/config.json" /tmp/tg_radar_config.bak
    echo -e "  ${TAG_WARN} 备份 ${RES} 检测到既存配置数据，已做安全留存。"
    RESTORE_CONFIG=true
fi

echo -ne "  ${MAIN}⠋${RES} 正在下载并部署系统环境..."
mkdir -p "$INSTALL_DIR"
rm -rf /tmp/tgr_main.zip /tmp/TG-Radar-main
curl -fsSL "https://github.com/${REPO}/archive/refs/heads/main.zip" -o /tmp/tgr_main.zip || { 
    echo -e "\n  ${TAG_ERR} 下载异常 ${RES} 获取应用包失败。"
    exit 1
}

unzip -q -o /tmp/tgr_main.zip -d /tmp/ >/dev/null 2>&1
cp -af /tmp/TG-Radar-main/. "$INSTALL_DIR/"
rm -rf /tmp/tgr_main.zip /tmp/TG-Radar-main
echo -e "\r  ${TAG_OK} 部署 ${RES} 核心源码拉取与就位完毕     "

if [ "$RESTORE_CONFIG" = true ]; then 
    cp /tmp/tg_radar_config.bak "$INSTALL_DIR/config.json"
    rm -f /tmp/tg_radar_config.bak
fi

echo "$LATEST_SHA" > "$COMMIT_FILE"
chmod +x "$INSTALL_DIR/deploy.sh" "$INSTALL_DIR/install.sh" 2>/dev/null || true

echo -ne "  ${MAIN}⠋${RES} 正在初始化系统环境变量..."
cat > "$GLOBAL_CMD" << 'TGREOF'
#!/bin/bash
exec bash /root/TG-Radar/deploy.sh "$@"
TGREOF
chmod +x "$GLOBAL_CMD"
echo -e "\r  ${TAG_OK} 变量 ${RES} 全局 TGR 命令注册完成 "

echo -e "\n  ${TAG_OK} 成功 ${RES} ${B}系统底层安装环节全部结束！${RES}"
echo -e "         即将进入主控制面板进行下一步配置 (2 秒后)...\n"
sleep 2
exec bash "$INSTALL_DIR/deploy.sh"
