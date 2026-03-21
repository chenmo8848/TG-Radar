#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
PLUGIN_DIR="$ROOT_DIR/plugins-external/TG-Radar-Plugins"
PREFIX=$(python3 - <<'PY'
import json, pathlib
path = pathlib.Path('config.json')
if path.exists():
    cfg = json.loads(path.read_text(encoding='utf-8'))
    print(cfg.get('service_name_prefix') or 'tg-radar')
else:
    print('tg-radar')
PY
)
echo "[1] Python venv:"
[[ -x .venv/bin/python ]] && echo "ok" || echo "missing"
echo "[2] config.json:"
[[ -f config.json ]] && echo "ok" || echo "missing"
echo "[3] sessions:"
ls -1 runtime/sessions/*.session 2>/dev/null || true
echo "[4] plugin repo:"
if [[ -d "$PLUGIN_DIR" ]]; then echo "$PLUGIN_DIR"; else echo "missing"; fi
echo "[5] services:"
systemctl status "${PREFIX}-admin" --no-pager -l 2>/dev/null | sed -n '1,6p' || true
systemctl status "${PREFIX}-core" --no-pager -l 2>/dev/null | sed -n '1,6p' || true
