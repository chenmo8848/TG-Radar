#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT_DIR/plugins-external/TG-Radar-Plugins"
mkdir -p "$ROOT_DIR/runtime/plugins"
ln -sfn "$TARGET" "$ROOT_DIR/runtime/plugins/TG-Radar-Plugins"
echo "已链接 $TARGET -> $ROOT_DIR/runtime/plugins/TG-Radar-Plugins"
