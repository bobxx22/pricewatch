"""Minimal synchronous Telegram Bot API client for sending alerts from Celery workers.

The aiogram bot runs in its own event loop; workers are synchronous, so they talk to the
Bot API with plain requests. The token is part of every URL, so it is scrubbed from
every error message that could end up in a log.
"""

from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramApiError(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BotBlockedError(TelegramApiError):
    """The user blocked the bot or deleted their account (HTTP 403)."""


class TelegramClient:
    def __init__(
        self, token: str, *, timeout: float = 10.0, session: requests.Session | None = None
    ) -> None:
        self._token = token
        self.timeout = timeout
        self.session = session or requests.Session()

    def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._call("sendMessage", payload)

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = API_URL.format(token=self._token, method=method)
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegramApiError(self._scrub(f"{method} failed: {exc}")) from None
        if data.get("ok"):
            return data
        code = data.get("error_code")
        description = self._scrub(str(data.get("description", "")))
        if code == 403:
            raise BotBlockedError(description)
        retry_after = (data.get("parameters") or {}).get("retry_after")
        raise TelegramApiError(f"{method}: {code} {description}", retry_after=retry_after)

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "<token>") if self._token else text


def get_client() -> TelegramClient | None:
    """A client for the configured bot, or None when TELEGRAM_BOT_TOKEN is not set."""
    token = settings.TELEGRAM_BOT_TOKEN
    return TelegramClient(token) if token else None
