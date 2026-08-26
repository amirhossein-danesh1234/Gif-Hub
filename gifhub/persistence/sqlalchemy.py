from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from gifhub.domain.ids import candidate_gif_id
from gifhub.domain.models import GifRecord, GifStatus, SearchableGif, Tag
from gifhub.domain.search import rank_gifs
from gifhub.domain.state import ensure_transition
from gifhub.domain.tags import seed_tags


class RepositoryError(RuntimeError):
    pass


class NotFoundError(RepositoryError):
    pass


class ValidationError(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


gif_tags = Table(
    "gif_tags",
    Base.metadata,
    Column("gif_submission_id", String(36), ForeignKey("gifs.submission_id"), primary_key=True),
    Column("tag_id", String(64), ForeignKey("tags.id"), primary_key=True),
)


class TagRow(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    gifs: Mapped[list["GifRow"]] = relationship(
        secondary=gif_tags,
        back_populates="tags",
        lazy="selectin",
    )


class GifRow(Base):
    __tablename__ = "gifs"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_gifs_sha256"),
        UniqueConstraint("id", name="uq_gifs_public_id"),
    )

    submission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_gif_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_mp4_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[list[TagRow]] = relationship(
        secondary=gif_tags,
        back_populates="gifs",
        lazy="selectin",
    )


def create_repository_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


class GifRepository:
    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_repository_engine(str(database_url))
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name == "postgresql":
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_gifs_title_fts "
                        "ON gifs USING GIN (to_tsvector('simple', coalesce(title, '')))"
                    )
                )
        with self.session_factory.begin() as session:
            self._seed_tags(session)

    def _seed_tags(self, session: Session) -> None:
        for tag in seed_tags():
            existing = session.get(TagRow, tag.id)
            if existing is None:
                session.add(
                    TagRow(
                        id=tag.id,
                        name=tag.name,
                        emoji=tag.emoji,
                        slug=tag.slug,
                        normalized_name=tag.normalized_name,
                        sort_order=tag.sort_order,
                        is_active=tag.is_active,
                    )
                )
                continue
            existing.name = tag.name
            existing.emoji = tag.emoji
            existing.slug = tag.slug
            existing.normalized_name = tag.normalized_name
            existing.sort_order = tag.sort_order
            existing.is_active = tag.is_active

    def list_tags(self) -> tuple[Tag, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(TagRow).where(TagRow.is_active).order_by(TagRow.sort_order)
            ).all()
        return tuple(self._tag_from_row(row) for row in rows)

    def create_draft(
        self,
        *,
        created_by: int | None,
        sha256: str | None = None,
        telegram_file_id: str | None = None,
    ) -> GifRecord:
        with self.session_factory.begin() as session:
            if sha256:
                existing = session.scalar(select(GifRow).where(GifRow.sha256 == sha256))
                if existing is not None:
                    return self._record_from_row(existing)
            row = GifRow(
                submission_id=str(uuid4()),
                status=GifStatus.DRAFT.value,
                sha256=sha256,
                telegram_file_id=telegram_file_id,
                created_by=created_by,
            )
            session.add(row)
            session.flush()
            return self._record_from_row(row)

    def attach_processed_assets(
        self,
        submission_id: UUID | str,
        *,
        sha256: str,
        file_gif_url: str,
        file_mp4_url: str,
        thumbnail_url: str,
        telegram_file_id: str | None = None,
    ) -> GifRecord:
        with self.session_factory.begin() as session:
            row = self._get_row(session, submission_id)
            row.sha256 = row.sha256 or sha256
            row.file_gif_url = file_gif_url
            row.file_mp4_url = file_mp4_url
            row.thumbnail_url = thumbnail_url
            row.telegram_file_id = telegram_file_id or row.telegram_file_id
            session.flush()
            return self._record_from_row(row)

    def submit_metadata(
        self,
        submission_id: UUID | str,
        *,
        title: str,
        tag_ids: tuple[str, ...],
        max_tags: int = 3,
    ) -> GifRecord:
        clean_title = " ".join(title.split())
        if not clean_title:
            raise ValidationError("Title is required.")
        if not tag_ids:
            raise ValidationError("At least one tag is required.")
        if len(tag_ids) > max_tags:
            raise ValidationError(f"At most {max_tags} tags are allowed.")

        with self.session_factory.begin() as session:
            row = self._get_row(session, submission_id)
            ensure_transition(GifStatus(row.status), GifStatus.PENDING)
            tags = self._get_tags(session, tag_ids)
            row.title = clean_title
            row.tags = list(tags)
            row.status = GifStatus.PENDING.value
            session.flush()
            return self._record_from_row(row)

    def approve_gif(
        self,
        submission_id: UUID | str,
        *,
        id_factory: Callable[[str, tuple[str, ...]], str] | None = None,
    ) -> GifRecord:
        factory = id_factory or candidate_gif_id
        with self.session_factory.begin() as session:
            row = self._get_row(session, submission_id, for_update=True)
            if GifStatus(row.status) == GifStatus.APPROVED:
                return self._record_from_row(row)
            ensure_transition(GifStatus(row.status), GifStatus.APPROVED)
            if not row.title or not row.tags:
                raise ValidationError("GIF must have title and tags before approval.")
            if not row.file_gif_url and not row.telegram_file_id:
                raise ValidationError("GIF has no deliverable asset.")

            tag_ids = tuple(tag.id for tag in row.tags)
            for _ in range(10):
                public_id = factory(row.title, tag_ids)
                if session.scalar(select(GifRow).where(GifRow.id == public_id)) is None:
                    row.id = public_id
                    break
            if row.id is None:
                raise ConflictError("Could not generate a unique GIF ID.")

            row.status = GifStatus.APPROVED.value
            row.approved_at = datetime.now(tz=UTC)
            session.flush()
            return self._record_from_row(row)

    def reject_gif(self, submission_id: UUID | str, *, reason: str | None = None) -> GifRecord:
        with self.session_factory.begin() as session:
            row = self._get_row(session, submission_id, for_update=True)
            if GifStatus(row.status) == GifStatus.REJECTED:
                return self._record_from_row(row)
            ensure_transition(GifStatus(row.status), GifStatus.REJECTED)
            row.status = GifStatus.REJECTED.value
            row.rejected_reason = reason
            session.flush()
            return self._record_from_row(row)

    def get_by_submission_id(self, submission_id: UUID | str) -> GifRecord:
        with self.session_factory() as session:
            return self._record_from_row(self._get_row(session, submission_id))

    def get_by_public_id(self, public_id: str, *, approved_only: bool = True) -> GifRecord:
        with self.session_factory() as session:
            statement = select(GifRow).where(GifRow.id == public_id)
            if approved_only:
                statement = statement.where(GifRow.status == GifStatus.APPROVED.value)
            row = session.scalar(statement)
            if row is None:
                raise NotFoundError("GIF not found.")
            return self._record_from_row(row)

    def increment_usage(self, public_id: str) -> GifRecord:
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(GifRow).where(
                    GifRow.id == public_id, GifRow.status == GifStatus.APPROVED.value
                )
            )
            if row is None:
                raise NotFoundError("GIF not found.")
            row.usage_count += 1
            session.flush()
            return self._record_from_row(row)

    def search(
        self,
        *,
        query: str = "",
        tag_ids: tuple[str, ...] = (),
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[tuple[GifRecord, ...], int | None]:
        page = max(page, 1)
        page_size = max(min(page_size, 50), 1)
        with self.session_factory() as session:
            rows = session.scalars(
                select(GifRow).where(GifRow.status == GifStatus.APPROVED.value)
            ).all()

        searchable = tuple(
            self._searchable_from_row(row) for row in rows if row.approved_at is not None
        )
        ranked = rank_gifs(searchable, query=query, query_tag_ids=tag_ids)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = ranked[start:end]
        next_page = page + 1 if len(ranked) > end else None
        by_id = {
            item.id: self._record_from_row(row)
            for row in rows
            for item in page_items
            if row.id == item.id
        }
        return tuple(by_id[item.id] for item in page_items), next_page

    def media_count(self) -> int:
        with self.session_factory() as session:
            return len(session.scalars(select(GifRow)).all())

    def _get_row(
        self, session: Session, submission_id: UUID | str, *, for_update: bool = False
    ) -> GifRow:
        statement = select(GifRow).where(GifRow.submission_id == str(submission_id))
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise NotFoundError("Submission not found.")
        return row

    def _get_tags(self, session: Session, tag_ids: tuple[str, ...]) -> tuple[TagRow, ...]:
        rows = session.scalars(select(TagRow).where(TagRow.id.in_(tag_ids), TagRow.is_active)).all()
        by_id = {row.id: row for row in rows}
        missing = [tag_id for tag_id in tag_ids if tag_id not in by_id]
        if missing:
            raise ValidationError(f"Invalid tag ids: {', '.join(missing)}")
        return tuple(by_id[tag_id] for tag_id in tag_ids)

    def _tag_from_row(self, row: TagRow) -> Tag:
        return Tag(
            id=row.id,
            name=row.name,
            emoji=row.emoji,
            slug=row.slug,
            normalized_name=row.normalized_name,
            sort_order=row.sort_order,
            is_active=row.is_active,
        )

    def _record_from_row(self, row: GifRow) -> GifRecord:
        return GifRecord(
            submission_id=UUID(row.submission_id),
            id=row.id,
            title=row.title,
            status=GifStatus(row.status),
            file_gif_url=row.file_gif_url,
            file_mp4_url=row.file_mp4_url,
            thumbnail_url=row.thumbnail_url,
            telegram_file_id=row.telegram_file_id,
            sha256=row.sha256,
            usage_count=row.usage_count,
            created_by=row.created_by,
            created_at=_ensure_aware(row.created_at),
            updated_at=_ensure_aware(row.updated_at),
            approved_at=_ensure_aware(row.approved_at) if row.approved_at else None,
            rejected_reason=row.rejected_reason,
            tags=tuple(
                self._tag_from_row(tag) for tag in sorted(row.tags, key=lambda tag: tag.sort_order)
            ),
        )

    def _searchable_from_row(self, row: GifRow) -> SearchableGif:
        return SearchableGif(
            id=str(row.id),
            title=row.title or "",
            tag_names=tuple(tag.name for tag in row.tags),
            tag_ids=tuple(tag.id for tag in row.tags),
            approved_at=_ensure_aware(row.approved_at or row.created_at),
            usage_count=row.usage_count,
        )


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
