#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if sys.platform == "win32":
        # A piped Windows console uses a legacy code page; don't crash on characters it lacks.
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="backslashreplace")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Did you run `uv sync` and use `uv run python manage.py ...`?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
