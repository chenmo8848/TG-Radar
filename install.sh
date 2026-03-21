#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

CONFIG_FILE="$ROOT_DIR/config.json"
EXAMPLE_FILE="$ROOT_DIR/config.example.json"
PLUGIN_DIR_DEFAULT="$ROOT_DIR/plugins-external/TG-Radar-Plugins"
mkdir -p "$ROOT_DIR/runtime/logs" "$ROOT_DIR/runtime/sessions" "$ROOT_DIR/runtime/plugins" "$ROOT_DIR/plugins-external"

command -v python3 >/dev/null 2>&1 || { echo "缺少 python3" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "缺少 git" >&2; exit 1; }

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f "$CONFIG_FILE" ]]; then
  cp "$EXAMPLE_FILE" "$CONFIG_FILE"
fi

python3 - <<'PY'
from pathlib import Path
import json, os
root = Path('.').resolve()
path = root / 'config.json'
cfg = json.loads(path.read_text(encoding='utf-8'))
plugins_repo = os.environ.get('PLUGINS_REPO_URL') or cfg.get('plugins_repo_url') or 'https://github.com/chenmo8848/TG-Radar-Plugins.git'
cfg['plugins_repo_url'] = plugins_repo
cfg['plugins_dir'] = './plugins-external/TG-Radar-Plugins'
if os.environ.get('API_ID'):
    cfg['api_id'] = int(os.environ['API_ID'])
if os.environ.get('API_HASH'):
    cfg['api_hash'] = os.environ['API_HASH']
if os.environ.get('GLOBAL_ALERT_CHANNEL_ID'):
    cfg['global_alert_channel_id'] = int(os.environ['GLOBAL_ALERT_CHANNEL_ID'])
if os.environ.get('NOTIFY_CHANNEL_ID'):
    cfg['notify_channel_id'] = int(os.environ['NOTIFY_CHANNEL_ID'])
if os.environ.get('SERVICE_NAME_PREFIX'):
    cfg['service_name_prefix'] = os.environ['SERVICE_NAME_PREFIX']
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
PY

API_ID_VALUE=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('api_id') or '')
PY
)
API_HASH_VALUE=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('api_hash') or '')
PY
)
if [[ -z "$API_ID_VALUE" || "$API_ID_VALUE" == "1234567" ]]; then
  read -r -p "请输入 Telegram API_ID: " INPUT_API_ID
  python3 - <<'PY' "$INPUT_API_ID"
from pathlib import Path
import json, sys
path = Path('config.json')
cfg = json.loads(path.read_text(encoding='utf-8'))
cfg['api_id'] = int(sys.argv[1])
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
PY
fi
if [[ -z "$API_HASH_VALUE" || "$API_HASH_VALUE" == "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]]; then
  read -r -p "请输入 Telegram API_HASH: " INPUT_API_HASH
  python3 - <<'PY' "$INPUT_API_HASH"
from pathlib import Path
import json, sys
path = Path('config.json')
cfg = json.loads(path.read_text(encoding='utf-8'))
cfg['api_hash'] = sys.argv[1]
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
PY
fi

PLUGIN_REPO_URL=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('plugins_repo_url') or 'https://github.com/chenmo8848/TG-Radar-Plugins.git')
PY
)
if [[ -d "$PLUGIN_DIR_DEFAULT/.git" ]]; then
  git -C "$PLUGIN_DIR_DEFAULT" pull --ff-only
elif [[ -d "$PLUGIN_DIR_DEFAULT" && -n "$(find "$PLUGIN_DIR_DEFAULT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "插件目录已存在且非 git 仓库：$PLUGIN_DIR_DEFAULT" >&2
  echo "请先清空该目录后重试。" >&2
  exit 1
else
  rm -rf "$PLUGIN_DIR_DEFAULT"
  git clone "$PLUGIN_REPO_URL" "$PLUGIN_DIR_DEFAULT"
fi

if [[ -f "$PLUGIN_DIR_DEFAULT/requirements.txt" ]]; then
  pip install -r "$PLUGIN_DIR_DEFAULT/requirements.txt"
fi

python3 src/bootstrap_session.py
python3 src/sync_once.py
bash deploy.sh
PREFIX=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('service_name_prefix') or 'tg-radar')
PY
)
systemctl daemon-reload
systemctl enable --now "${PREFIX}-admin" "${PREFIX}-core"

echo
echo "安装完成。"
echo "核心目录: $ROOT_DIR"
echo "插件目录: $PLUGIN_DIR_DEFAULT"
echo "服务名称: ${PREFIX}-admin / ${PREFIX}-core"
echo
echo "检查状态:"
systemctl status "${PREFIX}-admin" --no-pager -l | sed -n '1,12p'
systemctl status "${PREFIX}-core" --no-pager -l | sed -n '1,12p'
