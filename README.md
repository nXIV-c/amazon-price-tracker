# Amazon Price Tracker (Telegram bot)

A Telegram bot that watches amazon.de product prices and sends you a message when a price drops to the target you set.

## Features

- Guided `/add` flow or one-line `/add <link> <target price>`
- Messy links (tracking parameters, localized slugs) are normalized to `https://www.amazon.de/dp/<ASIN>`
- Background checker with request de-duplication, random delays and per-product error isolation
- One alert per price drop; the product is re-armed when the price rises above the target again
- Tracks unavailable products and alerts when they come back at the target price
- Deny-by-default access list, per-action rate limits, a cap on tracked products per user, SQLite storage

## How it works

```
Telegram ──► bot.py ──► client.py ──► parsing.py ──► ProductSnapshot
                │                                         │
                └──────────► database.py ◄── checker.py ──┘ (every 4 h, alerts.py decides)
```

| Module | Responsibility |
| --- | --- |
| `tracker/parsing.py` | Pure functions: link normalization, HTML → price. No network, easy to test |
| `tracker/client.py` | Downloads pages with `curl_cffi` (browser TLS fingerprint) |
| `tracker/checker.py` | Periodic job; one request per unique product |
| `tracker/alerts.py` | "Should we notify?" as a pure function |
| `tracker/bot.py` | Telegram handlers (HTML parse mode, all user text escaped) |
| `tracker/limits.py` | `RateLimiter`: one action per user per cooldown, no I/O |
| `tracker/config.py` | Settings from environment variables; refuses unsafe configurations |
| `tracker/database.py` | SQLite access, one short-lived connection per call |
| `scripts/inspect_html.py` | Developer tool: explains how the parser sees a saved page |

### Parsing principle: a wrong price is worse than no price

The price is read only from the main-offer containers (price block and buy box). Struck-through list prices and per-unit prices are skipped. Prices from carousels or ads are never used as a fallback. If no price is found, the page either says the product is unavailable (tracked as such) or the parser raises `ParseError`.

## Setup

Requires Python 3.10+.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in BOT_TOKEN and ALLOWED_USER_IDS
python main.py
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | required | Token from @BotFather |
| `ALLOWED_USER_IDS` | required | Comma-separated Telegram user IDs allowed to use the bot. Empty means the bot refuses to start |
| `ALLOW_EVERYONE` | `false` | Set `true` to run a public bot on purpose (the allow-list is then ignored) |
| `MAX_PRODUCTS_PER_USER` | `20` | How many different products one user may track |
| `TELEGRAM_API_URL` | – | Optional Telegram API proxy (`https://host/bot{0}/{1}`) |
| `DATABASE_PATH` | `data/tracker.db` | SQLite file |
| `CHECK_INTERVAL_SECONDS` | `14400` | Time between checks |
| `REQUEST_DELAY_SECONDS` | `5` | Base pause between Amazon requests (jittered) |
| `DEBUG_HTML_DIR` | – | Save HTML of pages that failed to parse (development only) |

## Security model

- **Deny by default.** Only users in `ALLOWED_USER_IDS` can use the bot; an empty list stops the bot at startup unless `ALLOW_EVERYONE=true` is set deliberately. The check runs first, before any command handler, and again for inline buttons
- **Untrusted input is validated.** Only `amazon.de` links are accepted, and the bot downloads a URL it builds itself from the 10-character ASIN (`https://www.amazon.de/dp/<ASIN>`), so a user cannot point it at another address or file. The same ASIN is used for debug file names
- **No SQL injection.** All queries use bound parameters; users can only delete their own records
- **No markup injection.** Product titles and URLs are HTML-escaped before they are sent
- **Abuse limits.** A cooldown per user for `/add` (3 s), `/list` (2 s) and delete buttons (1 s), plus a cap on tracked products so one user cannot make the bot flood Amazon with requests; the cap is checked before any Amazon request is made
- **Secrets stay out of Git.** The token lives in `.env`, which is listed in `.gitignore`
- Not covered here: securing the server itself (non-root user, SSH keys, firewall)

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## When a page cannot be parsed

Amazon changes its markup per category and per offer type. With `DEBUG_HTML_DIR=debug` set, the failing page is saved as `debug/<ASIN>.html`; then:

```bash
python -m scripts.inspect_html debug/<ASIN>.html
```

No bot run is needed to try this: open the product page in your browser, save it with `Ctrl+S` ("Web Page, complete") as `debug/<ASIN>.html` and run the command above. Do not save the "view source" tab, it is a different document.

The output shows every `.a-price` on the page with its container id, which tells you which selector to add in `tracker/parsing.py`. Add a minimal HTML fixture to `tests/test_parsing.py` for every new layout.

## Limitations

- **Region matters.** Amazon hides prices of many products when a page is requested from a region it does not deliver to (for example from a Russian server IP), and answers datacenter or VPN addresses with a CAPTCHA. The bot reports both cases instead of guessing. Run it from an EU address; it never tries to solve or bypass a CAPTCHA

- amazon.de only, prices in EUR (the domain is one constant in `parsing.py`)
- Scraping HTML is fragile and Amazon's terms restrict automated access. This project is educational; for production use consider an official source such as the Product Advertising API
- The guided `/add` flow keeps its state in memory and is lost on restart
