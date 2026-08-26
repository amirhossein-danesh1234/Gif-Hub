import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from redis import Redis

from gifhub.config import Settings
from gifhub.domain.hash import sha256_file
from gifhub.domain.models import GifRecord
from gifhub.domain.normalization import normalize_persian
from gifhub.domain.parser import parse_manual_tags
from gifhub.domain.tags import active_tag_map
from gifhub.media.processor import MediaProcessor
from gifhub.media.validation import sniff_media_type, validate_upload_size
from gifhub.persistence.sqlalchemy import GifRepository, NotFoundError, ValidationError


@dataclass(frozen=True)
class ProcessingJob:
    submission_id: str
    local_path: str
    telegram_file_id: str | None = None


class ProcessingQueue:
    def enqueue(self, job: ProcessingJob) -> None:
        raise NotImplementedError


class RedisProcessingQueue(ProcessingQueue):
    key = "gifhub:processing"

    def __init__(self, redis_url: str) -> None:
        self.client: Redis = Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, job: ProcessingJob) -> None:
        self.client.rpush(self.key, json.dumps(job.__dict__))

    def dequeue(self, *, timeout_seconds: int = 5) -> ProcessingJob | None:
        item = self.client.blpop(self.key, timeout=timeout_seconds)
        if item is None:
            return None
        _, payload = item
        data = json.loads(payload)
        return ProcessingJob(**data)


class InMemoryProcessingQueue(ProcessingQueue):
    def __init__(self) -> None:
        self.jobs: list[ProcessingJob] = []

    def enqueue(self, job: ProcessingJob) -> None:
        self.jobs.append(job)


class GifService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: GifRepository,
        processor: MediaProcessor | None = None,
        queue: ProcessingQueue | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.processor = processor
        self.queue = queue

    def create_upload(
        self,
        local_path: Path,
        *,
        created_by: int | None,
        telegram_file_id: str | None = None,
    ) -> GifRecord:
        validate_upload_size(local_path, self.settings.max_upload_bytes)
        sniff_media_type(local_path)
        digest = sha256_file(local_path)
        record = self.repository.create_draft(
            created_by=created_by,
            sha256=digest,
            telegram_file_id=telegram_file_id,
        )
        if self.queue is not None:
            self.queue.enqueue(
                ProcessingJob(
                    submission_id=str(record.submission_id),
                    local_path=str(local_path),
                    telegram_file_id=telegram_file_id,
                )
            )
        return record

    async def process_job(self, job: ProcessingJob) -> GifRecord:
        if self.processor is None:
            raise RuntimeError("Media processor is not configured.")
        processed = await self.processor.process_local_file(
            Path(job.local_path),
            media_id=job.submission_id,
        )
        return self.repository.attach_processed_assets(
            job.submission_id,
            sha256=processed.sha256,
            file_gif_url=self.public_url(processed.normalized_gif_key),
            file_mp4_url=self.public_url(processed.optimized_mp4_key),
            thumbnail_url=self.public_url(processed.thumbnail_key),
            telegram_file_id=job.telegram_file_id,
        )

    def submit_metadata(
        self, submission_id: UUID | str, *, title: str, tag_ids: tuple[str, ...]
    ) -> GifRecord:
        return self.repository.submit_metadata(
            submission_id,
            title=title,
            tag_ids=tag_ids,
            max_tags=self.settings.max_tags_per_media,
        )

    def approve(self, submission_id: UUID | str) -> GifRecord:
        return self.repository.approve_gif(submission_id)

    def reject(self, submission_id: UUID | str, *, reason: str | None = None) -> GifRecord:
        return self.repository.reject_gif(submission_id, reason=reason)

    def get_public_gif(self, public_id: str) -> GifRecord:
        return self.repository.get_by_public_id(public_id, approved_only=True)

    def send_gif(self, public_id: str) -> GifRecord:
        return self.repository.increment_usage(public_id)

    def search(
        self,
        *,
        q: str = "",
        tag: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[tuple[GifRecord, ...], int | None]:
        tag_ids = self._resolve_tag_filter(tag)
        return self.repository.search(query=q, tag_ids=tag_ids, page=page, page_size=page_size)

    def parse_tag_selection(self, value: str) -> tuple[str, ...]:
        parsed = parse_manual_tags(
            value, tags=self.repository.list_tags(), max_count=self.settings.max_tags_per_media
        )
        if parsed.invalid:
            raise ValidationError(", ".join(parsed.invalid))
        return tuple(tag.id for tag in parsed.valid)

    def public_url(self, storage_key: str) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/media/{storage_key.lstrip('/')}"

    def _resolve_tag_filter(self, tag: str | None) -> tuple[str, ...]:
        if not tag:
            return ()
        tag_map = active_tag_map(self.repository.list_tags())
        normalized = normalize_persian(tag)
        resolved = tag_map.get(tag) or tag_map.get(tag.lower()) or tag_map.get(normalized)
        if resolved is None:
            raise NotFoundError("Tag not found.")
        return (resolved.id,)
