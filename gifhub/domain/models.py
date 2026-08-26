from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID


class GifStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Backward-compatible import name for older modules/tests while the POC is upgraded.
SubmissionStatus = GifStatus


class AssetKind(StrEnum):
    ORIGINAL = "original"
    NORMALIZED_GIF = "normalized_gif"
    OPTIMIZED_MP4 = "optimized_mp4"
    THUMBNAIL = "thumbnail"


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    emoji: str
    slug: str
    normalized_name: str
    sort_order: int
    is_active: bool = True

    @property
    def display_name_fa(self) -> str:
        return self.name


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    content_type: str
    size_bytes: int
    local_path: Path | None = None


@dataclass(frozen=True)
class SearchableGif:
    id: str
    title: str
    tag_names: tuple[str, ...]
    tag_ids: tuple[str, ...]
    approved_at: datetime
    usage_count: int
    report_count: int = 0


SearchableMedia = SearchableGif


@dataclass(frozen=True)
class GifRecord:
    submission_id: UUID
    id: str | None
    title: str | None
    status: GifStatus
    file_gif_url: str | None
    file_mp4_url: str | None
    thumbnail_url: str | None
    telegram_file_id: str | None
    sha256: str | None
    usage_count: int
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    rejected_reason: str | None
    tags: tuple[Tag, ...]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)
