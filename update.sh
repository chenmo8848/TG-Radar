#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
PLUGIN_DIR="$ROOT_DIR/plugins-external/TG-Radar-Plugins"
if [[ ! -d .git ]]; then
  echo "当前核心目录不是 git 仓库：$ROOT_DIR" >&2
  exit 1
fi
git pull --ff-only
if [[ -d "$PLUGIN_DIR/.git" ]]; then
  git -C "$PLUGIN_DIR" pull --ff-only
else
  echo "插件仓库不存在或不是 git 仓库：$PLUGIN_DIR" >&2
fi
source .venv/bin/activate
pip install -r requirements.txt
if [[ -f "$PLUGIN_DIR/requirements.txt" ]]; then
  pip install -r "$PLUGIN_DIR/requirements.txt"
fi
python src/sync_once.py
bash deploy.sh
systemctl daemon-reload
PREFIX=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('service_name_prefix') or 'tg-radar')
PY
)
systemctl restart "${PREFIX}-admin" "${PREFIX}-core"
systemctl status "${PREFIX}-admin" --no-pager -l | sed -n '1,12p'
systemctl status "${PREFIX}-core" --no-pager -l | sed -n '1,12p'
