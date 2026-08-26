import shutil
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from gifhub.config import Settings, get_settings
from gifhub.domain.models import GifRecord
from gifhub.media.processor import MediaProcessor
from gifhub.media.validation import MediaValidationError
from gifhub.persistence.sqlalchemy import (
    ConflictError,
    GifRepository,
    NotFoundError,
    ValidationError,
)
from gifhub.services import GifService, RedisProcessingQueue
from gifhub.storage.local import LocalStorageBackend


class UploadResponse(BaseModel):
    submission_id: UUID
    status: str


class SubmitMetadataRequest(BaseModel):
    submission_id: UUID
    title: str
    tag_ids: list[str] = Field(min_length=1, max_length=3)


class AdminApproveRequest(BaseModel):
    submission_id: UUID


class AdminRejectRequest(BaseModel):
    submission_id: UUID
    reason: str | None = None


class SendGifRequest(BaseModel):
    gif_id: str


class TagResponse(BaseModel):
    id: str
    name: str
    emoji: str
    slug: str


class GifResponse(BaseModel):
    id: str | None
    submission_id: UUID
    title: str | None
    tags: list[TagResponse]
    file_gif_url: str | None
    file_mp4_url: str | None
    thumbnail_url: str | None
    status: str
    usage_count: int


class SearchResponse(BaseModel):
    results: list[GifResponse]
    page: int
    page_size: int
    next_page: int | None


def create_app(
    *,
    settings: Settings | None = None,
    repository: GifRepository | None = None,
    service: GifService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_repository = repository or GifRepository(resolved_settings.database_url)
    resolved_repository.initialize()
    if service is None:
        storage = LocalStorageBackend(resolved_settings.storage_dir)
        processor = MediaProcessor(settings=resolved_settings, storage=storage)
        service = GifService(
            settings=resolved_settings,
            repository=resolved_repository,
            processor=processor,
            queue=RedisProcessingQueue(resolved_settings.redis_url),
        )

    app = FastAPI(title="GIF-Hub", version="1.0.0")
    app.state.settings = resolved_settings
    app.state.repository = resolved_repository
    app.state.service = service

    def get_service() -> GifService:
        service_from_state: GifService = app.state.service
        return service_from_state

    def require_admin(x_admin_chat_id: Annotated[str | None, Header()] = None) -> None:
        admin_ids = app.state.settings.admin_chat_ids
        if not admin_ids:
            raise HTTPException(status_code=403, detail="No admins configured.")
        try:
            chat_id = int(x_admin_chat_id or "")
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Invalid admin header.") from exc
        if chat_id not in admin_ids:
            raise HTTPException(status_code=403, detail="Admin access required.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, int | str]:
        return {"status": "ready", "media_count": app.state.repository.media_count()}

    @app.get("/metrics")
    def metrics() -> Response:
        body = f"gifhub_media_total {app.state.repository.media_count()}\n"
        return Response(content=body, media_type="text/plain; version=0.0.4")

    @app.post("/upload", response_model=UploadResponse)
    def upload(
        upload_file: Annotated[UploadFile, File()],
        gif_service: Annotated[GifService, Depends(get_service)],
        created_by: int | None = None,
    ) -> UploadResponse:
        upload_dir = app.state.settings.data_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = upload_file.filename or "upload.bin"
        destination = upload_dir / filename.replace("\\", "_").replace("/", "_")
        with destination.open("wb") as handle:
            shutil.copyfileobj(upload_file.file, handle)
        try:
            record = gif_service.create_upload(destination, created_by=created_by)
        except MediaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return UploadResponse(submission_id=record.submission_id, status=record.status.value)

    @app.post("/submit-metadata", response_model=GifResponse)
    def submit_metadata(
        payload: SubmitMetadataRequest,
        gif_service: Annotated[GifService, Depends(get_service)],
    ) -> GifResponse:
        try:
            record = gif_service.submit_metadata(
                payload.submission_id,
                title=payload.title,
                tag_ids=tuple(payload.tag_ids),
            )
        except (NotFoundError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return gif_response(record)

    @app.post("/admin/approve", response_model=GifResponse, dependencies=[Depends(require_admin)])
    def approve(
        payload: AdminApproveRequest,
        gif_service: Annotated[GifService, Depends(get_service)],
    ) -> GifResponse:
        try:
            return gif_response(gif_service.approve(payload.submission_id))
        except (NotFoundError, ValidationError, ConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/admin/reject", response_model=GifResponse, dependencies=[Depends(require_admin)])
    def reject(
        payload: AdminRejectRequest,
        gif_service: Annotated[GifService, Depends(get_service)],
    ) -> GifResponse:
        try:
            return gif_response(gif_service.reject(payload.submission_id, reason=payload.reason))
        except (NotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/search", response_model=SearchResponse)
    def search(
        gif_service: Annotated[GifService, Depends(get_service)],
        q: str = "",
        tag: str | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> SearchResponse:
        try:
            records, next_page = gif_service.search(q=q, tag=tag, page=page, page_size=page_size)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return SearchResponse(
            results=[gif_response(record) for record in records],
            page=page,
            page_size=page_size,
            next_page=next_page,
        )

    @app.get("/gif/{gif_id}", response_model=GifResponse)
    def get_gif(
        gif_id: str,
        gif_service: Annotated[GifService, Depends(get_service)],
    ) -> GifResponse:
        try:
            return gif_response(gif_service.get_public_gif(gif_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/callback/send-gif", response_model=GifResponse)
    def callback_send_gif(
        payload: SendGifRequest,
        gif_service: Annotated[GifService, Depends(get_service)],
    ) -> GifResponse:
        try:
            return gif_response(gif_service.send_gif(payload.gif_id))
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/media/{storage_key:path}")
    def media(storage_key: str) -> FileResponse:
        root = app.state.settings.storage_dir.resolve()
        path = (root / storage_key).resolve()
        if root not in path.parents and path != root:
            raise HTTPException(status_code=400, detail="Invalid media path.")
        if not path.exists():
            raise HTTPException(status_code=404, detail="Media not found.")
        return FileResponse(path)

    return app


def gif_response(record: GifRecord) -> GifResponse:
    return GifResponse(
        id=record.id,
        submission_id=record.submission_id,
        title=record.title,
        tags=[
            TagResponse(id=tag.id, name=tag.name, emoji=tag.emoji, slug=tag.slug)
            for tag in record.tags
        ],
        file_gif_url=record.file_gif_url,
        file_mp4_url=record.file_mp4_url,
        thumbnail_url=record.thumbnail_url,
        status=record.status.value,
        usage_count=record.usage_count,
    )
