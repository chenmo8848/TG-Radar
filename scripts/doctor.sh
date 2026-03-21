#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
echo "[1] Python venv:"
[[ -x .venv/bin/python ]] && echo "ok" || echo "missing"
echo "[2] config.json:"
[[ -f config.json ]] && echo "ok" || echo "missing"
echo "[3] sessions:"
ls -1 runtime/sessions/*.session 2>/dev/null || true
echo "[4] plugin repo:"
if [[ -d /root/TG-Radar-Plugins ]]; then echo "/root/TG-Radar-Plugins"; else echo "missing"; fi
