import argparse
import asyncio
from pathlib import Path

import uvicorn

from gifhub.api.app import create_app
from gifhub.config import get_settings
from gifhub.media.processor import MediaProcessor
from gifhub.persistence.sqlalchemy import GifRepository
from gifhub.services import GifService, ProcessingJob, RedisProcessingQueue
from gifhub.storage.local import LocalStorageBackend
from gifhub.telegram.bot import TelegramBot


def build_service() -> GifService:
    settings = get_settings()
    repository = GifRepository(settings.database_url)
    repository.initialize()
    storage = LocalStorageBackend(settings.storage_dir)
    processor = MediaProcessor(settings=settings, storage=storage)
    return GifService(
        settings=settings,
        repository=repository,
        processor=processor,
        queue=RedisProcessingQueue(settings.redis_url),
    )


def seed_database() -> None:
    settings = get_settings()
    repository = GifRepository(settings.database_url)
    repository.initialize()
    print(f"Seeded database at {settings.database_url}")


def run_api() -> None:
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)


def run_bot() -> None:
    settings = get_settings()
    if not settings.telegram_enabled:
        raise SystemExit("TELEGRAM_ENABLED=false; set it to true to run the bot.")
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required.")
    service = build_service()
    bot = TelegramBot(settings=settings, service=service)
    asyncio.run(bot.run_long_polling())


def run_worker() -> None:
    service = build_service()
    queue = service.queue
    if not isinstance(queue, RedisProcessingQueue):
        raise SystemExit("Redis queue is required for the worker.")
    print("GIF-Hub worker started")
    while True:
        job = queue.dequeue(timeout_seconds=5)
        if job is None:
            continue
        asyncio.run(service.process_job(job))


def process_media() -> None:
    parser = argparse.ArgumentParser(
        description="Process one local media file through the GIF-Hub pipeline."
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--created-by", type=int, default=None)
    args = parser.parse_args()

    service = build_service()
    record = service.create_upload(args.input_file, created_by=args.created_by)
    asyncio.run(
        service.process_job(
            ProcessingJob(submission_id=str(record.submission_id), local_path=str(args.input_file))
        )
    )
    print(service.repository.get_by_submission_id(record.submission_id))
