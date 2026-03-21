from __future__ import annotations

import asyncio
from telethon import TelegramClient


class MessageIO:
    def __init__(self, client: TelegramClient) -> None:
        self.client = client
        self._bg_tasks: set[asyncio.Task] = set()

    async def reply(self, event, text: str, *, auto_delete: int = 0) -> None:
        msg = await self.client.send_message('me', text, reply_to=event.id, link_preview=False)
        if auto_delete > 0:
            self._spawn(self._delete_later(msg, auto_delete))

    async def reply_to_message_id(self, message_id: int, text: str, *, auto_delete: int = 0) -> None:
        msg = await self.client.send_message('me', text, reply_to=message_id, link_preview=False)
        if auto_delete > 0:
            self._spawn(self._delete_later(msg, auto_delete))

    async def notify(self, target, text: str, *, auto_delete: int = 0) -> None:
        msg = await self.client.send_message(target, text, link_preview=False)
        if auto_delete > 0:
            self._spawn(self._delete_later(msg, auto_delete))

    async def edit_or_reply(self, message_id: int | None, text: str, *, reply_to: int | None = None, auto_delete: int = 0) -> None:
        msg = None
        if message_id:
            try:
                msg = await self.client.edit_message('me', message_id, text)
            except Exception:
                msg = None
        if msg is None:
            msg = await self.client.send_message('me', text, reply_to=reply_to, link_preview=False)
        if auto_delete > 0:
            self._spawn(self._delete_later(msg, auto_delete))

    async def _delete_later(self, msg, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
