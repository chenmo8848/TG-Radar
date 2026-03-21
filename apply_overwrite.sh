#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TARGET_DIR="${1:-/root/TG-Radar}"

mkdir -p "$TARGET_DIR"
rsync -av --delete \
  --exclude 'runtime/' \
  --exclude '.git/' \
  "$SRC_DIR/" "$TARGET_DIR/"

chmod +x "$TARGET_DIR/install.sh" "$TARGET_DIR/deploy.sh"
if [ -d "$TARGET_DIR/scripts" ]; then
  find "$TARGET_DIR/scripts" -type f -name '*.sh' -exec chmod +x {} \;
fi

echo "已覆盖到: $TARGET_DIR"
echo "接下来执行:"
echo "  cd $TARGET_DIR"
echo "  bash deploy.sh restart"
