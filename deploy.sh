#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
PREFIX=$(python3 - <<'PY'
import json, pathlib
cfg = json.loads(pathlib.Path('config.json').read_text(encoding='utf-8'))
print(cfg.get('service_name_prefix') or 'tg-radar')
PY
)
ADMIN_UNIT="/etc/systemd/system/${PREFIX}-admin.service"
CORE_UNIT="/etc/systemd/system/${PREFIX}-core.service"
cat > "$ADMIN_UNIT" <<UNIT
[Unit]
Description=TG-Radar Admin Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
ExecStart=${ROOT_DIR}/.venv/bin/python ${ROOT_DIR}/src/radar_admin.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
cat > "$CORE_UNIT" <<UNIT
[Unit]
Description=TG-Radar Core Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
ExecStart=${ROOT_DIR}/.venv/bin/python ${ROOT_DIR}/src/radar_core.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "${PREFIX}-admin" "${PREFIX}-core"
echo "已部署并启动：${PREFIX}-admin / ${PREFIX}-core"
