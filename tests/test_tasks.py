import pytest

from apps.catalog.models import Product
from apps.catalog.tasks import check_product_task, enqueue_due_checks
from config.celery import app as celery_app
from scraping import FetchError
from tests.helpers import PROM_URL, FakeFetcher, load_html

pytestmark = pytest.mark.django_db


@pytest.fixture
def eager_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let apply() run retries in-process instead of raising celery.exceptions.Retry."""
    monkeypatch.setitem(celery_app.conf, "task_eager_propagates", False)


def test_enqueue_due_checks_queues_each_due_product_once(
    prom_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[int] = []
    monkeypatch.setattr(check_product_task, "delay", queued.append)

    assert enqueue_due_checks() == 1
    assert enqueue_due_checks() == 0
    assert queued == [prom_product.pk]


def test_check_product_task_returns_outcome(
    prom_product: Product, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("prom_product.html")

    result = check_product_task.apply(args=[prom_product.pk]).get()

    assert result["ok"] is True
    assert result["price"] == "399.00"


def test_check_product_task_skips_missing_products() -> None:
    assert check_product_task.apply(args=[404]).get() == {"product_id": 404, "skipped": True}


@pytest.mark.usefixtures("eager_retries")
def test_retryable_failure_is_retried_three_times(
    prom_product: Product, use_fake_fetcher: FakeFetcher
) -> None:
    use_fake_fetcher.pages[PROM_URL] = FetchError("HTTP 503", retryable=True)

    result = check_product_task.apply(args=[prom_product.pk]).get()

    assert len(use_fake_fetcher.requested) == 4  # first attempt + 3 retries
    assert result["ok"] is False
    assert result["retryable"] is True


@pytest.mark.usefixtures("eager_retries")
def test_parse_error_is_not_retried(prom_product: Product, use_fake_fetcher: FakeFetcher) -> None:
    use_fake_fetcher.pages[PROM_URL] = load_html("no_product.html")

    result = check_product_task.apply(args=[prom_product.pk]).get()

    assert len(use_fake_fetcher.requested) == 1
    assert result["ok"] is False
