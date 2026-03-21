from __future__ import annotations
import asyncio, shutil
from pathlib import Path
from telethon import TelegramClient
from tgr.compat import seed_db_from_legacy_config_if_needed
from tgr.config import load_config, sync_snapshot_to_config
from tgr.db import RadarDB
from tgr.logger import setup_logger

async def main() -> None:
    wd = Path(__file__).resolve().parent.parent
    cfg = load_config(wd)
    log = setup_logger("tg-radar-bootstrap", cfg.logs_dir / "bootstrap.log")
    db = RadarDB(cfg.db_path)
    seed_db_from_legacy_config_if_needed(wd, db)
    sync_snapshot_to_config(wd, db)
    cfg.sessions_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.sessions_dir / "tg_radar_bootstrap"

    print("\n\033[1mTG-Radar · Telegram 授权\033[0m")
    print("─" * 50)
    print("请按提示输入手机号、验证码、二步验证密码（如有）。\n")

    async with TelegramClient(str(tmp), cfg.api_id, cfg.api_hash) as client:
        await client.start()
        me = await client.get_me()
        name = getattr(me, "username", None) or getattr(me, "first_name", "?")
        log.info("authorized as %s", name)
        print(f"\033[32m✔\033[0m 已授权: {name}\n")

    src = tmp.with_suffix(".session")
    targets = [cfg.session_path.with_suffix(".session"), cfg.core_session.with_suffix(".session")]
    for t in targets:
        shutil.copy2(src, t)
    for f in [src, tmp.with_suffix(".session-journal"), tmp.with_suffix(".session-shm"), tmp.with_suffix(".session-wal")]:
        try: f.unlink(missing_ok=True)
        except: pass
    # Clean legacy worker session
    (cfg.sessions_dir / "tg_radar_admin_worker.session").unlink(missing_ok=True)

    print("Session 已写入:")
    for t in targets:
        print(f"  {t}")
    print("\n\033[32m✔\033[0m 授权完成。可以启动服务了。\n")

if __name__ == "__main__":
    asyncio.run(main())
