from __future__ import annotations

import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.bot.telegram.dispatcher import run_polling


class Command(BaseCommand):
    help = "Run the Telegram bot with long polling. Stop it with Ctrl+C."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set. Add it to .env (see .env.example).")
        self.stdout.write("Bot is running. Press Ctrl+C to stop.")
        try:
            asyncio.run(run_polling(settings.TELEGRAM_BOT_TOKEN))
        except KeyboardInterrupt:
            self.stdout.write("Bot stopped.")
