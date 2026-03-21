#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT_DIR/runtime/plugins"
ln -sfn /root/TG-Radar-Plugins "$ROOT_DIR/runtime/plugins/TG-Radar-Plugins"
echo "已链接 /root/TG-Radar-Plugins -> $ROOT_DIR/runtime/plugins/TG-Radar-Plugins"
