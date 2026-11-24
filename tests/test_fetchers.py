from __future__ import annotations

import pytest
import requests
from requests.utils import get_encoding_from_headers

from scraping import FetchError, HttpFetcher, RobotsDisallowedError
from scraping.fetchers import DEFAULT_USER_AGENT, clear_robots_cache

SHOP = "https://shop.example.com"
PAGE = f"{SHOP}/item/1"
ROBOTS = f"{SHOP}/robots.txt"


def make_response(
    status: int = 200, body: str = "", content_type: str = "text/html; charset=utf-8"
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = content_type
    # This is what requests does for a real response, including its ISO-8859-1 fallback.
    response.encoding = get_encoding_from_headers(response.headers)
    return response


class FakeSession:
    def __init__(self, responses: dict[str, requests.Response | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> requests.Response:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def _fresh_robots_cache() -> None:
    clear_robots_cache()


def fetcher_for(responses: dict[str, requests.Response | Exception], **kwargs: object):
    session = FakeSession(responses)
    return HttpFetcher(session=session, **kwargs), session  # type: ignore[arg-type]


def test_returns_page_and_caches_robots() -> None:
    robots = make_response(body="User-agent: *\nDisallow: /cart/\n", content_type="text/plain")
    fetcher, session = fetcher_for({ROBOTS: robots, PAGE: make_response(body="<h1>ok</h1>")})

    assert fetcher.get(PAGE) == "<h1>ok</h1>"
    assert fetcher.get(PAGE) == "<h1>ok</h1>"
    assert session.calls == [ROBOTS, PAGE, PAGE]


def test_robots_disallow_blocks_the_request() -> None:
    robots = make_response(body="User-agent: *\nDisallow: /item/\n", content_type="text/plain")
    fetcher, session = fetcher_for({ROBOTS: robots})

    with pytest.raises(RobotsDisallowedError) as error:
        fetcher.get(PAGE)

    assert error.value.retryable is False
    assert session.calls == [ROBOTS]


def test_missing_robots_txt_allows_everything() -> None:
    fetcher, _ = fetcher_for({ROBOTS: make_response(404), PAGE: make_response(body="ok")})

    assert fetcher.get(PAGE) == "ok"


def test_unavailable_robots_txt_is_a_retryable_error() -> None:
    fetcher, _ = fetcher_for({ROBOTS: make_response(503)})

    with pytest.raises(FetchError) as error:
        fetcher.get(PAGE)

    assert error.value.retryable is True


def test_robots_check_can_be_disabled() -> None:
    fetcher, session = fetcher_for({PAGE: make_response(body="ok")}, respect_robots_txt=False)

    assert fetcher.get(PAGE) == "ok"
    assert session.calls == [PAGE]


@pytest.mark.parametrize(
    ("status", "retryable"), [(404, False), (410, False), (403, False), (429, True), (503, True)]
)
def test_http_errors(status: int, retryable: bool) -> None:
    fetcher, _ = fetcher_for({PAGE: make_response(status)}, respect_robots_txt=False)

    with pytest.raises(FetchError) as error:
        fetcher.get(PAGE)

    assert error.value.retryable is retryable
    assert str(status) in str(error.value)


def test_network_errors_are_retryable() -> None:
    fetcher, _ = fetcher_for(
        {PAGE: requests.ConnectionError("connection reset")}, respect_robots_txt=False
    )

    with pytest.raises(FetchError, match="connection reset") as error:
        fetcher.get(PAGE)

    assert error.value.retryable is True


def test_cyrillic_without_charset_is_decoded_as_utf8() -> None:
    page = make_response(body="<h1>Клей для плитки</h1>", content_type="text/html")
    fetcher, _ = fetcher_for({PAGE: page}, respect_robots_txt=False)

    assert fetcher.get(PAGE) == "<h1>Клей для плитки</h1>"


def test_default_session_has_headers_and_retries() -> None:
    session = HttpFetcher().session

    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT
    assert session.get_adapter(PAGE).max_retries.total == 3
