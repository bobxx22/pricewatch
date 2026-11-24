from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from apps.bot.telegram.handlers import router
from apps.bot.telegram.middlewares import UserMiddleware

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="list", description="Мої товари"),
    BotCommand(command="help", description="Довідка"),
    BotCommand(command="cancel", description="Скасувати дію"),
]
STARTUP_ATTEMPTS = 5


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.message.outer_middleware(UserMiddleware())
    dispatcher.callback_query.outer_middleware(UserMiddleware())
    dispatcher.include_router(router)
    return dispatcher


def build_bot(token: str) -> Bot:
    return Bot(
        token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


async def run_polling(token: str) -> None:
    bot = build_bot(token)
    dispatcher = build_dispatcher()
    # bot.me() caches the profile, so start_polling does not ask Telegram for it again.
    me = await with_retry_after(bot.me)
    await with_retry_after(lambda: bot.set_my_commands(BOT_COMMANDS))
    logger.info("Starting @%s", me.username)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


async def with_retry_after[T](
    call: Callable[[], Awaitable[T]], attempts: int = STARTUP_ATTEMPTS
) -> T:
    """Run a Bot API call, waiting as long as Telegram asks when it answers 429."""
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            if attempt == attempts:
                raise
            logger.warning("Telegram asks to wait %s s (attempt %s)", exc.retry_after, attempt)
            await asyncio.sleep(exc.retry_after + 1)
    raise AssertionError("unreachable")
