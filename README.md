# PriceWatch

[![CI](https://github.com/bobxx22/pricewatch/actions/workflows/ci.yml/badge.svg)](https://github.com/bobxx22/pricewatch/actions/workflows/ci.yml)

PriceWatch tracks prices and stock of products in Ukrainian online shops. Send a product link to
the Telegram bot (or add it through the dashboard, admin or API), and PriceWatch re-checks it on a
schedule, keeps the price history, and messages you when the price drops, reaches your target, or
the item is back in stock.

![Dashboard: this week's price drops as shelf tags, the tracked products below](docs/screenshots/dashboard.png)

| Product page | Dark theme | Phone |
| --- | --- | --- |
| ![Product page with the price-history chart](docs/screenshots/product.png) | ![The same page in the dark theme](docs/screenshots/product-dark.png) | ![The dashboard on a phone](docs/screenshots/mobile.png) |

*Screenshots use the demo data from `manage.py seed_demo`: a made-up shop on a reserved
`.example` domain, never scraped.*

## What it shows

| Area | In this project |
| --- | --- |
| **Django + database** | Models built for history and scheduling, a service layer shared by every entry point, signals between apps, `select_for_update`, subquery and sliced-prefetch queries, an admin with actions |
| **Scraping: requests + BeautifulSoup** | JSON-LD (incl. `ProductGroup` variants and strikethrough prices), schema.org microdata, `data-*` attributes; robots.txt per RFC 9309, retries with backoff, polite rate limits |
| **Playwright** | A headless-browser fetcher for listings that only grow through a JavaScript "load more" button, with robots.txt checks, blocked heavy resources and HTTP status handling |
| **Telegram bot (aiogram 3)** | Add links, product cards with inline buttons, a target-price conversation (FSM), price history, alerts on drops and restocks |
| **API** | REST API on Django REST framework: filters, ordering, pagination, token auth, throttling, OpenAPI schema and Swagger UI |
| **Automation** | Celery + Redis: a beat job that claims due products, per-product checks with retries, alerts queued after the transaction commits |
| **Dashboard** | Server-rendered pages: weekly price drops, filters, sparklines, an SVG price-history chart with keyboard-accessible tooltips, CSV and Excel export |
| **Quality** | 220+ pytest tests on trimmed copies of real pages (network blocked), live canaries, browser tests in real Chromium; CI runs ruff, the tests on PostgreSQL and Redis, and builds the Docker image |

## Architecture

```mermaid
flowchart LR
    user([Telegram user]) <--> bot[aiogram bot]
    bot --> services
    admin[Django admin] --> services
    api[REST API] --> services
    dash[Dashboard] --> db
    beat[Celery beat] -->|every 5 min| enqueue[claim due products]
    enqueue --> redis[(Redis)]
    redis --> worker[Celery worker]
    worker --> services[catalog.services]
    services --> scraping[scraping: fetchers + parsers]
    scraping -->|HTTPS| shops[Online shops]
    services --> db[(PostgreSQL)]
    services -. product_changed signal .-> alerts[bot alerts task]
    alerts -->|Bot API| user
```

- `apps/catalog`: shops, products, price snapshots and all business logic (`services.py`).
- `apps/bot`: Telegram users, subscriptions, the aiogram bot and price alerts.
- `apps/api`: the REST API. `apps/dashboard`: the web pages and exports.
- `scraping/`: framework-free fetchers and parsers. No Django imports, tested on saved HTML.

| Model | Purpose |
| --- | --- |
| `Shop` | Domain, display name, a switch for all its products |
| `Product` | URL, latest price, old price and stock status, `next_check_at` for scheduling, last error |
| `PriceSnapshot` | One history point, written only when the price, old price or stock status changes |
| `TelegramUser`, `Subscription` | Who follows which product, with an optional target price |

## Supported shops

| Shop | Product pages | Category listings |
| --- | --- | --- |
| Rozetka | JSON-LD `ProductGroup`: the variant for the URL, old price from `StrikethroughPrice` | Server-rendered, `.../page=N/`, read over HTTP |
| Prom.ua | JSON-LD, plus the pre-discount price from `data-qaid="old_price"` | — |
| Epicentr K | schema.org microdata and `data-product-price-*` attributes | — |
| [webscraper.io test shop](https://webscraper.io/test-sites/e-commerce/more) | microdata | Rendered by JavaScript, grows with a "More" button: read in headless Chromium |
| Any other shop | JSON-LD or microdata `Product` (`@graph`, offer lists, `AggregateOffer`, `ImageObject`) | — |

### Why the browser is used where it is

Every Ukrainian shop checked for this project (Rozetka, Prom, Epicentr, Telemart, KTC, Kasta,
Metro) renders product data on the server, so plain HTTP is faster and enough. A browser earns its
keep on listings that are built by JavaScript, so that is the only place PriceWatch uses one.
Two findings shaped this:

- Rozetka's "Показати ще" button moves to a `page=1,2/` URL, which its robots.txt disallows
  (`Disallow: /*,*`). The scanner reads the allowed `page=N/` URLs instead.
- One grocery chain answers plain requests with HTTP 403 but serves a headless browser. That is a
  block, and PriceWatch respects it: the browser is never used to get around bot protection.

## Telegram bot

Send the bot a product link: it checks the page right away and replies with a card.

| | |
| --- | --- |
| `/start`, `/help` | What the bot does |
| a product link | Start tracking; the card shows price, discount, stock and shop |
| `/list` | Your products, one button per product |
| 🎯 Target price | Alerts only once the price is at or below your number (`0` removes it) |
| 📈 History | The latest price changes |
| 🗑 Unsubscribe | Stop tracking |

Alerts arrive when a price drops (or reaches the target) and when an item is back in stock.
Users who block the bot are switched off automatically. The bot talks Ukrainian.

```bash
uv run python manage.py runbot      # long polling; TELEGRAM_BOT_TOKEN in .env
```

## REST API

Reading is public; changing data needs a staff account (token or session). Docs at `/api/docs/`.

| Method and path | |
| --- | --- |
| `GET /api/products/` | Filters: `q`, `shop`, `in_stock`, `on_sale`, `min_price`, `max_price`; `ordering=price`, `-discount`… |
| `GET /api/products/{id}/` | One product |
| `GET /api/products/{id}/history/` | Price history, oldest first |
| `POST /api/products/` | `{"url": "..."}`: start tracking, the first check is queued |
| `POST /api/products/{id}/check/` | Check now (202 when queued) |
| `PATCH /api/products/{id}/` | Pause or resume with `is_active` |
| `GET /api/shops/` | Shops with product counts |
| `POST /api/token/` | Get a token for a username and password |

```bash
curl -s "http://127.0.0.1:8000/api/products/?on_sale=true&ordering=-discount"
curl -s -X POST http://127.0.0.1:8000/api/products/ \
     -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
     -d '{"url": "https://rozetka.com.ua/ua/samsung-sm-s931bzkgeuc/p525186024/"}'
```

## Quick start (without Docker)

You need Python 3.12+ (developed on 3.14) and [uv](https://docs.astral.sh/uv/). Background checks
need Redis or a compatible server (on Windows, [Memurai](https://www.memurai.com/) works).

```bash
uv sync
cp .env.example .env                       # optional: every setting has a default
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo          # optional demo data
uv run python manage.py runserver          # http://127.0.0.1:8000/
```

Track and check products:

```bash
uv run python manage.py add_product "https://prom.ua/ua/p2970749786-olivkovoe-maslo-monini.html" --check
uv run python manage.py check_prices --all          # all products, without Celery
uv run python manage.py scan_category "https://rozetka.com.ua/ua/mobile-phones/c80003/" --pages 2 --max-price 10000
```

Background work:

```bash
uv run celery -A config worker --loglevel=info   # on Windows add --pool=solo
uv run celery -A config beat --loglevel=info
uv run python manage.py runbot
```

The browser is only needed for "load more" listings: `uv run playwright install chromium`, or set
`PLAYWRIGHT_CHANNEL=chrome` to use the installed Google Chrome.

## With Docker

```bash
docker compose up --build                    # PostgreSQL, Redis, web, worker, beat, bot
docker compose exec web python manage.py createsuperuser
```

Production on one server: put a TLS proxy (Caddy, nginx) in front of port 8000, fill in `.env`
(`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_HTTPS=true`,
`TELEGRAM_BOT_TOKEN`, a real database password), then:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The image runs gunicorn with WhiteNoise for static files and ships headless Chromium. CI builds it,
validates both compose files and starts Chromium inside it on every push.

## Configuration

All settings come from environment variables or `.env`; see [.env.example](.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | SQLite file | e.g. `postgres://user:password@host:5432/pricewatch` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Celery broker |
| `TELEGRAM_BOT_TOKEN` | empty | Bot token from @BotFather; without it the bot and alerts are off |
| `PRICE_CHECK_INTERVAL_MINUTES` | `60` | How often each product is re-checked |
| `SCRAPER_RESPECT_ROBOTS_TXT` | `true` | Skip URLs that robots.txt disallows |
| `SCRAPER_RATE_LIMIT` | `30/m` | Celery rate limit for price checks, per worker |
| `PLAYWRIGHT_CHANNEL` | empty | `chrome` to use the installed Chrome |
| `DASHBOARD_LOGIN_REQUIRED` | `false` | Put the dashboard behind the admin login |
| `DJANGO_HTTPS` | `false` | Secure cookies, HSTS and HTTPS redirect behind a TLS proxy |

## Tests

```bash
uv run pytest                 # unit, integration and browser tests; no network
uv run pytest -m live         # check the parsers against the real shops
uv run ruff check . && uv run ruff format --check .
```

Browser tests run when Chromium is available (`PLAYWRIGHT_CHANNEL=chrome` works locally); CI
installs it and fails if they cannot run.

## Responsible scraping

PriceWatch reads public product pages only. It honours robots.txt, keeps delays and rate limits,
backs off on errors, and treats HTTP 401/403 as a closed door: no CAPTCHA solving, no stealth
browsers, no getting around blocks. Test fixtures are trimmed to the elements the parsers read.

## Roadmap

- [x] Models, admin, parsers (requests + BeautifulSoup), management commands
- [x] Celery scheduling, retries and price history
- [x] Telegram bot: links, cards, target prices, alerts
- [x] Playwright fetcher and category scanning
- [x] Dashboard with price charts, REST API, CSV and Excel export
- [x] Production setup: gunicorn, WhiteNoise, HTTPS settings, compose override
- [ ] Deployment to a public server with a demo link
- [ ] Category watches in the bot ("tell me when anything here drops below X")

The dashboard's design rules are in [DESIGN.md](DESIGN.md).
