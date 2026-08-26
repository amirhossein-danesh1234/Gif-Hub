# GIF-Hub

GIF-Hub is a Telegram-first GIF library bot with click-based search, short human-readable
GIF IDs, admin moderation, PostgreSQL persistence, and Redis-backed async media processing.

## Architecture

- FastAPI modular monolith for upload, metadata, admin, search, GIF lookup, and send callbacks.
- Telegram bot adapter for `/start`, `/upload`, `/search`, inline send buttons, admin review,
  and manual GIF ID fallback.
- PostgreSQL repository using SQLAlchemy with Alembic migrations.
- Redis queue and `gifhub-worker` for FFmpeg processing outside request/bot handlers.
- Local filesystem storage for development; public media URLs are generated from `PUBLIC_BASE_URL`.

## Core UX

Search results are rendered as:

```text
🎬 {TITLE}
#{GIF_ID}

Tags: <tag1> <tag2> <tag3>

[▶ Send GIF]
```

Users send content with one click. As a fallback, they can send a short ID such as
`laugh-cat-83k`.

## API

- `POST /upload`
- `POST /submit-metadata`
- `POST /admin/approve`
- `POST /admin/reject`
- `GET /search`
- `GET /gif/{id}`
- `POST /callback/send-gif`

Admin endpoints require `X-Admin-Chat-Id`, which must be present in
`TELEGRAM_ADMIN_CHAT_IDS`.

## Run

```powershell
Copy-Item .env.example .env
docker compose up --build api worker
```

Run the bot profile after setting `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and
`TELEGRAM_ADMIN_CHAT_IDS`:

```powershell
docker compose --profile bot up --build
```

## Local Checks

```powershell
pytest -q
ruff check .
mypy gifhub
docker compose config --quiet
```
