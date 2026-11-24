from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from asgiref.sync import sync_to_async
from django.db import close_old_connections

from apps.bot import services
from apps.bot.models import TelegramUser


class UserMiddleware(BaseMiddleware):
    """Registers whoever writes to the bot and hands the record to handlers as `tg_user`."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user: User | None = data.get("event_from_user")
        if from_user is not None and not from_user.is_bot:
            data["tg_user"] = await sync_to_async(_register)(from_user)
        return await handler(event, data)


def _register(user: User) -> TelegramUser:
    # The bot is a long-running process without request signals: drop stale DB connections.
    close_old_connections()
    return services.register_user(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        language_code=user.language_code or "",
    )
