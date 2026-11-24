from django.apps import AppConfig


class BotConfig(AppConfig):
    name = "apps.bot"
    label = "bot"
    verbose_name = "Telegram bot"

    def ready(self) -> None:
        from apps.bot import receivers  # noqa: F401  (connects to catalog signals)
