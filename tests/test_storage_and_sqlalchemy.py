from pathlib import Path

import pytest

from gifhub.domain.models import GifStatus
from gifhub.persistence.sqlalchemy import GifRepository, ValidationError
from gifhub.storage.local import LocalStorageBackend


@pytest.fixture()
def repository(tmp_path: Path) -> GifRepository:
    repo = GifRepository(f"sqlite:///{tmp_path / 'gifhub.sqlite3'}")
    repo.initialize()
    return repo


@pytest.mark.asyncio
async def test_local_storage_put_get_exists_and_blocks_traversal(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path / "storage")
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")

    stored = await storage.put_file(source, "media/1/original/file.txt", "text/plain")
    assert stored.size_bytes == 5
    assert await storage.exists("media/1/original/file.txt")

    destination = tmp_path / "out.txt"
    await storage.get_file("media/1/original/file.txt", destination)
    assert destination.read_text(encoding="utf-8") == "hello"

    with pytest.raises(ValueError):
        await storage.exists("../escape.txt")


def test_upload_metadata_pending_approve_and_search(repository: GifRepository) -> None:
    record = repository.create_draft(created_by=100, sha256="abc123", telegram_file_id="tg-file")
    repository.attach_processed_assets(
        record.submission_id,
        sha256="abc123",
        file_gif_url="https://cdn/gif.gif",
        file_mp4_url="https://cdn/gif.mp4",
        thumbnail_url="https://cdn/thumb.jpg",
        telegram_file_id="tg-file",
    )
    pending = repository.submit_metadata(
        record.submission_id,
        title="Laugh Cat",
        tag_ids=("laugh", "interesting"),
    )

    assert pending.status == GifStatus.PENDING
    assert repository.search(tag_ids=("laugh",))[0] == ()

    approved = repository.approve_gif(
        record.submission_id,
        id_factory=lambda title, tags: "laugh-cat-83k",
    )

    assert approved.id == "laugh-cat-83k"
    results, next_page = repository.search(tag_ids=("laugh",), page=1, page_size=10)
    assert [item.id for item in results] == ["laugh-cat-83k"]
    assert next_page is None


def test_reject_with_reason(repository: GifRepository) -> None:
    record = repository.create_draft(created_by=100, sha256="reject")
    pending = repository.submit_metadata(record.submission_id, title="Bad GIF", tag_ids=("laugh",))
    rejected = repository.reject_gif(pending.submission_id, reason="not suitable")

    assert rejected.status == GifStatus.REJECTED
    assert rejected.rejected_reason == "not suitable"


def test_duplicate_upload_returns_existing_submission(repository: GifRepository) -> None:
    first = repository.create_draft(created_by=100, sha256="same")
    second = repository.create_draft(created_by=200, sha256="same")

    assert second.submission_id == first.submission_id
    assert second.created_by == 100


def test_invalid_tags_and_missing_title_are_rejected(repository: GifRepository) -> None:
    record = repository.create_draft(created_by=100, sha256="invalid")

    with pytest.raises(ValidationError):
        repository.submit_metadata(record.submission_id, title="", tag_ids=("laugh",))

    with pytest.raises(ValidationError):
        repository.submit_metadata(record.submission_id, title="Title", tag_ids=("missing",))

    with pytest.raises(ValidationError):
        repository.submit_metadata(
            record.submission_id,
            title="Title",
            tag_ids=("laugh", "happy", "excited", "hype"),
        )
