"""Checks against real services. CI sets REQUIRE_SERVICES=1, so a missing Redis fails the run there;
locally the test is skipped when no broker is running."""

import os

import pytest
from kombu.exceptions import OperationalError

from config.celery import app as celery_app

pytestmark = pytest.mark.integration


def test_message_round_trip_through_the_broker() -> None:
    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=1)
            queue = connection.SimpleQueue("pricewatch.selftest")
            try:
                queue.put({"ping": "pong"})
                message = queue.get(timeout=5)
                message.ack()
            finally:
                queue.close()
    except (OperationalError, OSError) as exc:
        if os.environ.get("REQUIRE_SERVICES"):
            raise
        pytest.skip(f"Broker is not reachable: {exc}")

    assert message.payload == {"ping": "pong"}
