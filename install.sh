#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [[ -f config.example.json && ! -f config.json ]]; then
  cp config.example.json config.json
fi
mkdir -p runtime/logs runtime/sessions runtime/plugins
if [[ -d /root/TG-Radar-Plugins && ! -e runtime/plugins/TG-Radar-Plugins ]]; then
  ln -s /root/TG-Radar-Plugins runtime/plugins/TG-Radar-Plugins
fi
if [[ -f /root/TG-Radar-Plugins/requirements.txt ]]; then
  pip install -r /root/TG-Radar-Plugins/requirements.txt
fi
cat <<'MSG'

TG-Radar 核心已安装。
下一步：
1) 编辑 config.json，填入 api_id / api_hash
2) 如插件仓库位于 /root/TG-Radar-Plugins，无需额外修改 plugins_dir
3) 执行：source .venv/bin/activate && python src/bootstrap_session.py
4) 首次同步：source .venv/bin/activate && python src/sync_once.py
5) 部署 systemd：./deploy.sh
MSG
