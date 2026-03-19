#!/bin/bash
# ============================================================
#  TG-Radar 态势感知引擎 · 核心部署管家 v5.1.1
# ============================================================
set -e

INSTALL_DIR="/root/TG-Radar"
SERVICE_NAME="tg_monitor"
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; RESET='\033[0m'; DIM='\033[2m'

_svc_active() { systemctl is-active --quiet $SERVICE_NAME; }
_svc_enabled() { systemctl is-enabled --quiet $SERVICE_NAME 2>/dev/null; }

show_menu() {
    clear
    echo -e "  ${CYAN}▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰${RESET}"
    echo -e "         ${BOLD}TG-Radar 态势感知引擎 · 核心部署管家${RESET}"
    echo -e "                       v5.1.1                         "
    echo -e "  ${CYAN}▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰${RESET}\n"

    # 状态栏：采用硬编码空格，确保 2 空格对齐
    if _svc_active; then
        echo -e "  ${GREEN}●${RESET}  服务    运行中"
    elif _svc_enabled; then
        echo -e "  ${YELLOW}●${RESET}  服务    已停止 ${DIM}(自启已注册)${RESET}"
    else
        echo -e "  ${RED}●${RESET}  服务    未启动"
    fi

    if [ -f "$INSTALL_DIR/config.json" ]; then
        echo -e "  ${GREEN}●${RESET}  配置    就绪"
    else
        echo -e "  ${RED}●${RESET}  配置    缺失"
    fi

    if [ -x "/usr/local/bin/TGR" ]; then
        echo -e "  ${GREEN}●${RESET}  TGR     已注册"
    else
        echo -e "  ${RED}●${RESET}  TGR     未注册"
    fi

    echo -e "  ${DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
    
    # 菜单栏：采用 3 空格对齐序号
    echo -e "   1   一键部署  全程引导：环境 + 配置 + 授权"
    echo -e "   2   停止服务"
    echo -e "   3   启动服务"
    echo -e "   4   重启服务"
    echo -e "   5   状态与日志"
    echo -e "   6   重新授权  session 失效 / 切换账号"
    echo -e "   7   完全卸载"
    echo -e "   0   退出\n"
    printf "  请输入选项 [0-7] ："
}

while true; do
    show_menu
    read -r opt
    case $opt in
        1) bash <(curl -fsSL https://raw.githubusercontent.com/chenmo8848/TG-Radar/main/install.sh); break ;;
        2) sudo systemctl stop $SERVICE_NAME; echo "服务已停止"; sleep 1 ;;
        3) sudo systemctl start $SERVICE_NAME; echo "服务已启动"; sleep 1 ;;
        4) sudo systemctl restart $SERVICE_NAME; echo "服务已重启"; sleep 1 ;;
        5) clear; echo -e "${CYAN}--- 系统状态 ---${RESET}"; sudo systemctl status $SERVICE_NAME --no-pager || true; \
           echo -e "\n${CYAN}--- 最近 20 行日志 ---${RESET}"; journalctl -u $SERVICE_NAME -n 20 --no-pager; read -p "按回车返回..." ;;
        6) cd $INSTALL_DIR && rm -f *.session*; echo "凭证已清理，请重新运行一键部署进行授权。"; sleep 2 ;;
        7) read -p "确定要完全卸载吗？(y/n): " confirm; if [[ $confirm == [yY] ]]; then \
           sudo systemctl stop $SERVICE_NAME || true; sudo systemctl disable $SERVICE_NAME || true; \
           sudo rm -f /etc/systemd/system/$SERVICE_NAME.service; sudo systemctl daemon-reload; \
           sudo rm -f /usr/local/bin/TGR; echo "卸载完成。"; exit 0; fi ;;
        0) exit 0 ;;
        *) echo "无效选项"; sleep 1 ;;
    esac
done
