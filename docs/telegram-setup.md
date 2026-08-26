# Telegram Setup

1. Create a bot with BotFather.
2. Copy the bot token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Set `TELEGRAM_ENABLED=true`.
4. Keep `TELEGRAM_USE_LONG_POLLING=true` for Phase 0 development.
5. Start the bot with `gifhub-bot`.

Useful BotFather commands:

- `/setcommands`: configure `/start`, `/help`, `/upload`, `/search`, `/tags`, `/cancel`.
- `/setinline`: enable inline mode before testing inline queries.

Phase 0 uses Telegram long polling and direct Bot API calls. Production webhook setup is deferred to Phase 2.
