"""initial gifhub schema

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260616_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("normalized_name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tags_slug", "tags", ["slug"])

    op.create_table(
        "gifs",
        sa.Column("submission_id", sa.String(length=36), primary_key=True),
        sa.Column("id", sa.String(length=96), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_gif_url", sa.Text(), nullable=True),
        sa.Column("file_mp4_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("telegram_file_id", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("id", name="uq_gifs_public_id"),
        sa.UniqueConstraint("sha256", name="uq_gifs_sha256"),
    )
    op.create_index("ix_gifs_id", "gifs", ["id"])
    op.create_index("ix_gifs_status", "gifs", ["status"])
    op.create_index("ix_gifs_usage_count", "gifs", ["usage_count"])
    op.create_index("ix_gifs_created_by", "gifs", ["created_by"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gifs_title_fts "
        "ON gifs USING GIN (to_tsvector('simple', coalesce(title, '')))"
    )

    op.create_table(
        "gif_tags",
        sa.Column("gif_submission_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["gif_submission_id"], ["gifs.submission_id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("gif_submission_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("gif_tags")
    op.drop_index("ix_gifs_title_fts", table_name="gifs")
    op.drop_index("ix_gifs_created_by", table_name="gifs")
    op.drop_index("ix_gifs_usage_count", table_name="gifs")
    op.drop_index("ix_gifs_status", table_name="gifs")
    op.drop_index("ix_gifs_id", table_name="gifs")
    op.drop_table("gifs")
    op.drop_index("ix_tags_slug", table_name="tags")
    op.drop_table("tags")
