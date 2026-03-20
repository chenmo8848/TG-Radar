#!/bin/bash
# ============================================================
#  TG-Radar  —  Management Script (Enterprise Version)
#  Path : /root/TG-Radar
#  Cmd  : TGR
# ============================================================
set -uo pipefail

# ── Colors ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

MAIN='\033[36m'        
TEXT='\033[37m'        
TAG_OK='\033[42;30m'   
TAG_ERR='\033[41;37m'  
TAG_WARN='\033[43;30m' 

_i() { echo -e "${CYAN} ➜  ${RESET}$*"; }
_ok(){ echo -e "${GREEN} ✔  ${RESET}$*"; }
_w() { echo -e "${YELLOW} ⚠  ${RESET}$*"; }
_e() { echo -e "${RED} ✖  ${RESET}$*"; }
_bar(){ echo -e "  ${DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }
_pause(){ echo ""; read -rp "  按回车键返回系统菜单 ..." _DUMMY; }

# ── Constants ────────────────────────────────────────────────
APP_DIR="/root/TG-Radar"
SVC="tg_monitor"
SVC_FILE="/etc/systemd/system/${SVC}.service"
SYNC_BIN="$APP_DIR/sync_engine.py"
MON_BIN="$APP_DIR/tg_monitor.py"
PY="$APP_DIR/venv/bin/python3"
TGR_CMD="/usr/local/bin/TGR"
REPO="chenmo8848/TG-Radar"
COMMIT_FILE="$APP_DIR/.commit_sha"

# ── Helpers ──────────────────────────────────────────────────
_svc_active()  { systemctl is-active  --quiet "$SVC" 2>/dev/null; }
_svc_enabled() { systemctl is-enabled --quiet "$SVC" 2>/dev/null; }
_cfg_ok()      { [ -f "$APP_DIR/config.json" ]; }
_api_ok() {
    _cfg_ok || return 1
    local id
    id=$(python3 -c "import json; print(json.load(open('$APP_DIR/config.json')).get('api_id',''))" 2>/dev/null || true)
    [ -n "$id" ] && [ "$id" != "1234567" ]
}

_try_start() {
    sudo systemctl start "$SVC" 2>/dev/null && sleep 1 || true
    _svc_active && _ok "监控服务已启动" || _e "启动失败  →  journalctl -u $SVC -n 20"
}

_startup_update_check() {
    local api_res remote_sha local_sha short_remote short_local dl_url
    
    api_res=$(curl -fsSL --connect-timeout 3 "https://api.github.com/repos/${REPO}/commits/main" 2>/dev/null) || return 0
    remote_sha=$(echo "$api_res" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)
    [ -z "$remote_sha" ] && return 0
    
    local_sha=""
    [ -f "$COMMIT_FILE" ] && local_sha=$(cat "$COMMIT_FILE")
    
    if [ "$remote_sha" = "$local_sha" ]; then return 0; fi

    short_remote=${remote_sha:0:7}
    
    clear
    echo -e "\n${MAIN}${BOLD} ▌ 发现系统更新 ${RESET}\n"
    echo -e "  最新版本:  ${TAG_OK} ${short_remote} ${RESET}\n"
    _bar
    echo ""
    echo -e "  ${BOLD}${GREEN}1${RESET}  一键同步更新  ${DIM}(覆盖源码并自动重启服务，配置数据保留)${RESET}"
    echo -e "  ${BOLD}${CYAN}2${RESET}  重新部署环境  ${DIM}(更新源码后重新执行配置引导)${RESET}"
    echo -e "  ${BOLD}3${RESET}  跳过本次更新  ${DIM}(保持现状)${RESET}"
    echo ""
    read -rp "  请选择 [1/2/3，默认=3] ➔ " _upd
    _upd="${_upd:-3}"
    echo ""

    case "$_upd" in
        1|2)
            _i "正在拉取最新代码 (版本: ${short_remote})..."
            dl_url="https://github.com/${REPO}/archive/refs/heads/main.zip"
            
            if curl -fsSL "$dl_url" -o /tmp/tgr_main_update.zip 2>/dev/null; then
                [ -f "$APP_DIR/config.json" ] && cp "$APP_DIR/config.json" /tmp/_tgr_cfg.bak
                rm -rf /tmp/TG-Radar-main
                unzip -q -o /tmp/tgr_main_update.zip -d /tmp/ 2>/dev/null
                cp -af /tmp/TG-Radar-main/. "$APP_DIR/" 2>/dev/null
                [ -f /tmp/_tgr_cfg.bak ] && cp /tmp/_tgr_cfg.bak "$APP_DIR/config.json" && rm -f /tmp/_tgr_cfg.bak
                rm -rf /tmp/tgr_main_update.zip /tmp/TG-Radar-main
                chmod +x "$APP_DIR/deploy.sh" "$APP_DIR/install.sh" 2>/dev/null || true
                echo "$remote_sha" > "$COMMIT_FILE"
                _ok "已同步至最新版本 [${short_remote}]"
                echo ""
                
                if [ "$_upd" = "1" ]; then
                    _i "正在重启系统进程..."
                    sudo systemctl restart "$SVC" 2>/dev/null && sleep 1 || true
                    _svc_active && _ok "系统已重启，更新生效。" || _w "重启失败  →  journalctl -u $SVC -n 20"
                    echo -e "\n  ${GREEN}${BOLD}更新完成！所有配置数据已保留。${RESET}\n"
                    read -rp "  按回车键进入管理菜单 ..." _DUMMY
                    exec bash "$APP_DIR/deploy.sh"
                else
                    echo -e "  ${GREEN}即将重载部署向导...${RESET}"
                    sleep 2
                    exec bash "$APP_DIR/deploy.sh"
                fi
            else
                _w "拉取代码失败，继续使用当前版本。"
                echo ""
                read -rp "  按回车键继续 ..." _DUMMY
            fi
            ;;
        *)
            _i "已跳过更新。"
            sleep 1
            ;;
    esac
}

_startup_update_check

_menu() {
    clear
    echo -e "\n${MAIN}${BOLD} ▌ TG-RADAR 系统管理终端 ${RESET}"
    echo -e "${MAIN} │${RESET}"

    echo -e "${MAIN} ├─ ${BOLD}${TEXT}系统状态${RESET}"
    if _svc_active; then
        echo -e "${MAIN} │  ${DIM}后台进程    ${RESET}${TAG_OK}  运行中  ${RESET}"
    elif _svc_enabled; then
        echo -e "${MAIN} │  ${DIM}后台进程    ${RESET}${TAG_WARN}  已挂起  ${RESET} ${DIM} 开机自启开启${RESET}"
    else
        echo -e "${MAIN} │  ${DIM}后台进程    ${RESET}${TAG_ERR}  未启动  ${RESET}"
    fi

    if _api_ok; then
        echo -e "${MAIN} │  ${DIM}核心配置    ${RESET}${TAG_OK}  已就绪  ${RESET}"
    elif _cfg_ok; then
        echo -e "${MAIN} │  ${DIM}核心配置    ${RESET}${TAG_WARN}  待填写  ${RESET}"
    else
        echo -e "${MAIN} │  ${DIM}核心配置    ${RESET}${TAG_ERR}  已缺失  ${RESET}"
    fi

    if [ -x "$TGR_CMD" ]; then
        echo -e "${MAIN} │  ${DIM}全局环境    ${RESET}${TAG_OK}  已注册  ${RESET} ${DIM} 任意终端输入 TGR 即可唤出${RESET}"
    else
        echo -e "${MAIN} │  ${DIM}全局环境    ${RESET}${TAG_ERR}  未注册  ${RESET}"
    fi
    
    echo -e "${MAIN} │${RESET}"
    echo -e "${MAIN} ├─ ${BOLD}${TEXT}常规指令${RESET}"
    echo -e "${MAIN} │  ${BOLD}1${RESET}  执行自动部署初始化"
    echo -e "${MAIN} │  ${BOLD}2${RESET}  停止系统后台进程"
    echo -e "${MAIN} │  ${BOLD}3${RESET}  启动系统后台进程"
    echo -e "${MAIN} │  ${BOLD}4${RESET}  重启系统及重载配置"
    echo -e "${MAIN} │${RESET}"
    echo -e "${MAIN} ├─ ${BOLD}${TEXT}高级维护${RESET}"
    echo -e "${MAIN} │  ${BOLD}5${RESET}  查看实时运行日志"
    echo -e "${MAIN} │  ${BOLD}6${RESET}  更新 Telegram 账号授权"
    echo -e "${MAIN} │  ${BOLD}7${RESET}  彻底卸载并清理环境"
    echo -e "${MAIN} │${RESET}"
    echo -e "${MAIN} │  ${DIM}0  退出菜单${RESET}"
    echo -e "${MAIN} │${RESET}"
}

_deploy() {
    clear; echo ""; echo -e "${BOLD}  ╔══════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}  ║                   系统初始化向导                     ║${RESET}"
    echo -e "${BOLD}  ╚══════════════════════════════════════════════════════╝${RESET}"
    echo ""; echo -e "  ${DIM}1. 部署环境  ·  2. 绑定参数  ·  3. 鉴权启动${RESET}"; echo ""

    read -rp "  按回车键开始部署 (Ctrl+C 取消) ：" _DUMMY; echo ""

    _bar; echo -e "  ${BOLD}第一步：部署系统环境${RESET}"; _bar; echo ""
    declare -a _RES=(); _PASS=0; _TOTAL=5

    _step() {
        local n="$1" label="$2"; shift 2
        echo -ne "  [${n}/${_TOTAL}]  ${label} ..."
        if "$@" > /tmp/tgr_deploy.log 2>&1; then
            echo -e "  ${GREEN}完成${RESET}"; _PASS=$((_PASS+1)); _RES+=("${GREEN}  ✓${RESET}  ${label}")
        else
            echo -e "  ${RED}失败${RESET}"; _RES+=("${RED}  ✗${RESET}  ${label}  ${DIM}(可查看 /tmp/tgr_deploy.log)${RESET}")
        fi
    }

    _step 1 "安装基础依赖包" bash -c "apt-get update -y >/dev/null && apt-get install -y python3 python3-venv python3-pip cron >/dev/null"
    _step 2 "创建应用目录" bash -c "mkdir -p '$APP_DIR'; chmod +x '$APP_DIR/deploy.sh'"
    _step 3 "配置 Python 运行环境" bash -c "cd '$APP_DIR'; [ ! -d venv ] && python3 -m venv venv; ./venv/bin/pip install --upgrade pip >/dev/null; ./venv/bin/pip install telethon requests >/dev/null"
    _step 4 "注册后台守护服务" bash -c "
        printf '[Unit]\nDescription=TG-Radar Service\nAfter=network.target\n\n[Service]\nType=simple\nUser=root\nWorkingDirectory=$APP_DIR\nExecStart=$PY $MON_BIN\nRestart=always\nRestartSec=5\nStandardOutput=journal\nStandardError=journal\n\n[Install]\nWantedBy=multi-user.target\n' > '$SVC_FILE'
        systemctl daemon-reload && systemctl enable '$SVC' >/dev/null 2>&1
    "
    _step 5 "注册 TGR 全局命令" bash -c "
        printf '#!/bin/bash\nexec bash /root/TG-Radar/deploy.sh \"\$@\"\n' > '$TGR_CMD'
        chmod +x '$TGR_CMD'
        tmp_cron=\$(mktemp)
        crontab -l > \"\$tmp_cron\" 2>/dev/null || true
        sed -i '/sync_engine\.py/d' \"\$tmp_cron\" 2>/dev/null || true
        sed -i '/journalctl.*vacuum/d' \"\$tmp_cron\" 2>/dev/null || true
        echo '0 3 * * * journalctl --vacuum-time=1d >/dev/null 2>&1' >> \"\$tmp_cron\"
        crontab \"\$tmp_cron\"
        rm -f \"\$tmp_cron\"
    "

    echo ""; _bar; echo -e "  部署结果： ${_PASS}/${_TOTAL} 项任务已完成"; _bar
    if [ "$_PASS" -lt "$_TOTAL" ]; then echo ""; _e "环境部署存在异常，流程中止。"; _pause; return; fi
    echo ""; echo -e "  ${GREEN}环境就绪，即将进入参数配置...${RESET}"; sleep 2

    clear; echo ""; _bar; echo -e "  ${BOLD}第二步：绑定参数${RESET}"; _bar; echo ""
    if _api_ok; then
        local _cid
        _cid=$(python3 -c "import json; print(json.load(open('$APP_DIR/config.json')).get('api_id',''))" 2>/dev/null)
        echo -e "  检测到历史配置  ${DIM}API_ID = ${_cid}${RESET}\n"
        read -rp "  保留现有配置并跳过此步骤？[Y/n] ：" _skip
        _skip="${_skip:-Y}"
        if [ "$_skip" = "Y" ] || [ "$_skip" = "y" ]; then _ok "已应用现有配置。"; sleep 1; else _fill_config; fi
    else _fill_config; fi

    clear; echo ""; _bar; echo -e "  ${BOLD}第三步：账号鉴权与启动${RESET}"; _bar; echo ""
    echo -e "  ${DIM}系统即将尝试登录 Telegram 并拉取您的群组列表。${RESET}\n"
    read -rp "  按回车键继续 (Ctrl+C 取消) ：" _DUMMY; echo ""

    cd "$APP_DIR"; "$PY" "$SYNC_BIN" --chatops; local _exit=$?

    echo ""; _bar; echo -e "  ${BOLD}运行结果检查${RESET}"; _bar; echo ""
    local _ok=true
    [ -f "$SVC_FILE" ]  && _ok "后台服务正常"      || { _e "服务注册失败";      _ok=false; }
    [ -f "$PY" ]        && _ok "运行环境正常"     || { _e "Python 环境异常";   _ok=false; }
    [ -f "$TGR_CMD" ]   && _ok "管理命令正常"      || { _e "命令注册失败";      _ok=false; }
    _api_ok             && _ok "配置参数正常" || { _e "配置文件缺失"; _ok=false; }

    if [ "$_exit" -eq 0 ]; then
        _ok "Telegram 账号鉴权通过"; sleep 1
        if _svc_active; then _ok "监控进程已启动"
        else _w "监控进程未启动，正在尝试手动拉起..."; _try_start; fi
    else
        _e "Telegram 账号鉴权失败"
        echo -e "  ${DIM}可能原因：参数有误、验证码超时或网络阻断。${RESET}"; _ok=false
    fi

    echo ""; _bar
    if [ "$_ok" = true ]; then
        local _pfx
        _pfx=$(python3 -c "import json; print(json.load(open('$APP_DIR/config.json')).get('cmd_prefix','-'))" 2>/dev/null || echo "-")
        echo ""; echo -e "  ${GREEN}${BOLD}恭喜！系统已成功部署并上线。${RESET}\n"
        echo -e "  ${BOLD}现在，请在您的 Telegram 客户端 [Saved Messages / 收藏夹] 中发送：${RESET}"
        echo -e "  ${CYAN}${_pfx}help${RESET} 获取详细的管理菜单。\n"
    else
        echo ""; _w "系统部署存在异常，请检查上述错误信息后重试选项 1。"
    fi
    _pause
}

_fill_config() {
    echo -e "  ${YELLOW}请前往 https://my.telegram.org 获取您的 API 凭证。${RESET}\n"
    local _id _hash
    while true; do read -rp "  输入 API_ID（纯数字）：" _id; [[ "$_id" =~ ^[0-9]+$ ]] && [ "$_id" != "1234567" ] && break; _w "格式无效。"; done
    while true; do read -rp "  输入 API_HASH：       " _hash; [ ${#_hash} -ge 16 ] && break; _w "长度不足，请检查。"; done

    python3 - << PYEOF2
import json, os
path = '$APP_DIR/config.json'
cfg  = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
cfg.update({'api_id': int('$_id'), 'api_hash': '$_hash'})
for k,v in [('folder_rules',{}),('_system_cache',{}),('global_alert_channel_id',None),('notify_channel_id',None),('cmd_prefix','-'),('auto_route_rules',{})]:
    cfg.setdefault(k,v)
tmp = path+'.tmp'; json.dump(cfg,open(tmp,'w',encoding='utf-8'),indent=4,ensure_ascii=False); os.replace(tmp,path)
PYEOF2

    echo ""; _i "尝试连接 Telegram，加载您的分组与频道列表..."; echo -e "  ${YELLOW}首次登录需在下方输入国家代码、手机号与验证码${RESET}\n"
    local _fetch
    _fetch=$("$PY" - << 'PYEOF3'
import asyncio, json
from telethon import TelegramClient, functions, types, utils
APP = '/root/TG-Radar'
async def run():
    cfg = json.load(open(f'{APP}/config.json', encoding='utf-8'))
    c   = TelegramClient(f'{APP}/TG_Radar_session', cfg['api_id'], cfg['api_hash'])
    await c.start()
    res = await c(functions.messages.GetDialogFiltersRequest())
    fds = [f for f in getattr(res,'filters',[]) if isinstance(f, types.DialogFilter)]
    folders=[]
    for f in fds:
        t = f.title.text if hasattr(f.title,'text') else str(f.title)
        ids=set()
        for peer in f.include_peers:
            try:
                pid = utils.get_peer_id(peer)
                t_name = type(peer).__name__
                if 'Channel' in t_name: ids.add(int(f"-100{pid}"))
                elif 'Chat' in t_name: ids.add(int(f"-{pid}"))
                else: ids.add(pid)
            except: pass
        if getattr(f,'groups',False) or getattr(f,'broadcasts',False):
            async for d in c.iter_dialogs():
                if f.groups and d.is_group: ids.add(d.id)
                elif f.broadcasts and d.is_channel and not d.is_group: ids.add(d.id)
        folders.append({'id':f.id,'title':t,'group_ids':list(ids)})
    channels=[]
    async for d in c.iter_dialogs():
        if d.is_channel and not d.is_group: channels.append({'id':d.id,'name':d.name})
    await c.disconnect()
    print('__JSON__'+json.dumps({'folders':folders,'channels':channels},ensure_ascii=False))
asyncio.run(run())
PYEOF3
)
    local _json; _json=$(echo "$_fetch" | grep '__JSON__' | sed 's/__JSON__//')
    if [ -z "$_json" ]; then _e "数据拉取超时或失败，请确认 API 凭证及网络连通性。"; return 1; fi
    _ok "获取数据成功！\n"; echo -e "  ${BOLD}请选择系统需要主动监控的 TG 分组${RESET}  ${DIM}（多个编号用空格分隔，直接回车 = 全选）${RESET}\n"

    local _fcnt; _fcnt=$(echo "$_json" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['folders']))")
    echo "$_json" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  {i})  {f[\"title\"]}  (共 {len(f[\"group_ids\"])} 个群)') for i,f in enumerate(d['folders'],1)]"
    echo ""
    if [ "$_fcnt" -eq 0 ]; then _w "您的账号尚未创建任何 Telegram 分组文件夹。"; return 1; fi

    local _sel
    while true; do
        read -rp "  请输入要监控的分组编号：" _sel
        [ -z "$_sel" ] && _sel=$(seq 1 "$_fcnt" | tr '\n' ' ')
        local _ok_sel=true
        for n in $_sel; do if ! [[ "$n" =~ ^[0-9]+$ ]] || [ "$n" -lt 1 ] || [ "$n" -gt "$_fcnt" ]; then _ok_sel=false; break; fi; done
        [ "$_ok_sel" = true ] && break
        _w "输入格式有误，请重新输入。"
    done

    echo ""; echo -e "  已选中下列分组："; echo "$_json" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  + {d[\"folders\"][int(i)-1][\"title\"]}') for i in '$_sel'.split()]"
    echo ""; echo -e "  ${BOLD}请选择报警通知接收频道${RESET}\n"
    
    local _chnc; _chnc=$(echo "$_json" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['channels']))")
    echo "$_json" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  {i})  {c[\"name\"]}  ({c[\"id\"]})') for i,c in enumerate(d['channels'],1)]"
    echo ""

    local _alert_ch
    if [ "$_chnc" -eq 0 ]; then
        _w "当前账号未加入任何频道，请手动输入报警频道的 ID。"
        while true; do read -rp "  输入接收通知的频道 ID：" _alert_ch; [[ "$_alert_ch" =~ ^-?[0-9]+$ ]] && break; done
    else
        while true; do
            read -rp "  输入对应的编号 [1-${_chnc}] (或直接粘贴频道ID) ：" _s
            if [[ "$_s" =~ ^[0-9]+$ ]] && [ "$_s" -ge 1 ] && [ "$_s" -le "$_chnc" ]; then
                _alert_ch=$(echo "$_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['channels'][$_s-1]['id'])")
                break
            elif [[ "$_s" =~ ^-?[0-9]+$ ]]; then _alert_ch="$_s"; break; fi
        done
    fi

    echo ""; echo -e "  ${BOLD}系统信息通知频道${RESET}  ${DIM}（选填，直接回车则默认与上述报警频道相同）${RESET}\n"
    local _notify_ch _notify_val
    read -rp "  输入系统通知频道 ID：" _notify_ch
    [[ "${_notify_ch:-}" =~ ^-?[0-9]+$ ]] && _notify_val="$_notify_ch" || _notify_val="null"

    echo ""; local _pfx; read -rp "  设置 TG 聊天指令前缀 (直接回车默认使用 '-')：" _pfx; _pfx="${_pfx:--}"
    _i "正在为您保存配置文件..."
    echo "$_json" > /tmp/_tgr_data.json
    
    # 🚨 此处已彻底剔除旧版带 🟢 emoji 的病灶，保证初始化即纯净规范！
    python3 - << PYEOF7
import json, os
data = json.load(open('/tmp/_tgr_data.json', encoding='utf-8'))
sel  = [int(x)-1 for x in '$_sel'.split()]
path = '$APP_DIR/config.json'
cfg  = json.load(open(path, encoding='utf-8'))
cfg['api_id']                  = int('$_id')
cfg['api_hash']                = '$_hash'
cfg['global_alert_channel_id'] = int('$_alert_ch')
cfg['notify_channel_id']       = $_notify_val if '$_notify_val' != 'null' else None
cfg['cmd_prefix']              = '$_pfx'
cfg.setdefault('auto_route_rules', {})
fr={}; sc={}
for i in sel:
    f=data['folders'][i]; t=f['title']
    fr[t]={'id':f['id'],'enable':True,'alert_channel_id':None,'rules':{f'{t}监控':'(示范词A|示范词B)'}}
    sc[t]=f['group_ids']
cfg['folder_rules']=fr; cfg['_system_cache']=sc
tmp=path+'.tmp'; json.dump(cfg,open(tmp,'w',encoding='utf-8'),indent=4,ensure_ascii=False); os.replace(tmp,path)
os.remove('/tmp/_tgr_data.json')
PYEOF7

    echo -e "\n  ${GREEN}基础配置已生成完成！${RESET}\n  2 秒后进入系统鉴权阶段..."; sleep 2
}

_stop() { clear; echo -e "\n  ${BOLD}停止后台进程${RESET}\n"; if ! _svc_active; then _w "服务当前未运行。"; _pause; return; fi; sudo systemctl stop "$SVC" 2>/dev/null && _ok "进程已停止。" || _e "停止进程失败"; _pause; }
_start() { clear; echo -e "\n  ${BOLD}启动后台进程${RESET}\n"; [ ! -f "$SVC_FILE" ] && { _e "服务未安装或核心文件缺失。"; _pause; return; }; if _svc_active; then _w "服务已在运行中。"; _pause; return; fi; sudo systemctl start "$SVC" 2>/dev/null && sleep 1 || true; if _svc_active; then _ok "进程启动成功。"; else _e "启动失败"; fi; _pause; }
_restart() { clear; echo -e "\n  ${BOLD}重启系统服务${RESET}\n"; [ ! -f "$SVC_FILE" ] && { _e "服务未安装或核心文件缺失。"; _pause; return; }; sudo systemctl restart "$SVC" 2>/dev/null && sleep 1 || true; if _svc_active; then _ok "系统已重启，配置生效。"; else _e "重启失败"; fi; _pause; }
_status() { clear; echo -e "\n  ${BOLD}系统实时状态${RESET}\n"; _svc_active && echo -e "  ${GREEN}●${RESET} 后台进程运行中" || echo -e "  ${RED}○${RESET} 进程停止或处于错误状态"; echo ""; journalctl -u "$SVC" -n 20 --no-pager 2>/dev/null || true; _pause; }
_reauth() { clear; echo -e "\n  ${BOLD}刷新账号鉴权${RESET}\n"; cd "$APP_DIR"; "$PY" "$SYNC_BIN" --chatops; [ $? -eq 0 ] && _ok "账号授权凭证更新成功" || _e "鉴权失败，请重试"; _pause; }
_uninstall() { clear; echo -e "\n  ${BOLD}${RED}卸载并清理环境${RESET}\n"; read -rp "  确认删除所有服务及任务? (输入 yes 继续): " c; [ "$c" != "yes" ] && return; systemctl stop "$SVC" 2>/dev/null; systemctl disable "$SVC" 2>/dev/null; rm -f "$SVC_FILE"; rm -f "$TGR_CMD"; crontab -l | grep -v 'sync_engine' | crontab -; _ok "环境与任务清理完毕，您可直接删除 /root/TG-Radar 目录。"; _pause; }

while true; do
    _menu
    printf "\n${MAIN} ╰─➤ ${RESET}${BOLD}请输入指令编号 [0-7]: ${RESET}"
    read -r _choice
    echo ""
    case "$_choice" in 1) _deploy;; 2) _stop;; 3) _start;; 4) _restart;; 5) _status;; 6) _reauth;; 7) _uninstall;; 0) echo -e "  ${GREEN}终端已断开。${RESET}\n"; exit 0;; *) _w "指令无效，请重新输入。"; sleep 1;; esac
done
