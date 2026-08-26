# Architecture

GIF-Hub is now a modular monolith with production-oriented boundaries:

- `gifhub.domain`: pure status, tag, normalization, short ID, and ranking logic.
- `gifhub.persistence`: SQLAlchemy repository and PostgreSQL schema for GIFs, tags, and joins.
- `gifhub.services`: application use cases shared by API, bot, and worker.
- `gifhub.media`: validation, probing, and FFmpeg conversion.
- `gifhub.storage`: local storage abstraction used by the media worker in development.
- `gifhub.api`: upload, metadata, admin moderation, search, lookup, and send callback endpoints.
- `gifhub.telegram`: Telegram Bot API adapter and click-based UX flows.

Runtime services:

- FastAPI handles HTTP requests and never runs blocking FFmpeg work inline.
- Redis stores processing jobs.
- `gifhub-worker` consumes jobs and writes processed asset URLs back to PostgreSQL.
- The Telegram bot uses `telegram_file_id` for one-click delivery and falls back to public GIF URLs.

Search only returns `approved` GIFs. Results are ranked with:

```text
(tag_match * 3) + (title_match * 2) + log1p(usage_count) - (age_penalty * 0.5)
```

Public GIF IDs are generated at approval time and are short, readable, non-sequential strings such as
`laugh-cat-83k`.
