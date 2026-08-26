from pathlib import Path

from gifhub.domain.models import GifStatus, SearchableGif
from gifhub.persistence.sqlalchemy import GifRepository


class SQLiteStore:
    """Compatibility adapter for the old POC tests and commands."""

    def __init__(self, database_path: Path) -> None:
        self.repository = GifRepository(f"sqlite:///{database_path}")

    def initialize(self) -> None:
        self.repository.initialize()

    def create_or_get_media(self, media_id: str, sha256: str) -> str:
        record = self.repository.create_draft(created_by=None, sha256=sha256)
        return record.id or str(record.submission_id)

    def update_assets(
        self,
        media_id: str,
        *,
        original_key: str,
        normalized_gif_key: str,
        optimized_mp4_key: str,
        thumbnail_key: str,
        status: GifStatus = GifStatus.PENDING,
    ) -> None:
        record = self.repository.get_by_submission_id(media_id)
        self.repository.attach_processed_assets(
            record.submission_id,
            sha256=record.sha256 or media_id,
            file_gif_url=normalized_gif_key,
            file_mp4_url=optimized_mp4_key,
            thumbnail_url=thumbnail_key,
        )

    def set_media_tags(self, media_id: str, tag_ids: tuple[int, ...] | tuple[str, ...]) -> None:
        tag_lookup = self.repository.list_tags()
        resolved = tuple(
            tag_lookup[int(tag_id) - 1].id if isinstance(tag_id, int) else str(tag_id)
            for tag_id in tag_ids
        )
        self.repository.submit_metadata(media_id, title="Legacy GIF", tag_ids=resolved)

    def approve_media(self, media_id: str) -> None:
        self.repository.approve_gif(media_id)

    def searchable_media(self) -> tuple[SearchableGif, ...]:
        records, _ = self.repository.search(page=1, page_size=50)
        return tuple(
            SearchableGif(
                id=str(record.id),
                title=record.title or "",
                tag_names=tuple(tag.name for tag in record.tags),
                tag_ids=tuple(tag.id for tag in record.tags),
                approved_at=record.approved_at or record.created_at,
                usage_count=record.usage_count,
            )
            for record in records
        )

    def media_count(self) -> int:
        return self.repository.media_count()
