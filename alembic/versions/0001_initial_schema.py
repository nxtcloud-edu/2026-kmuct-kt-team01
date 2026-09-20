"""Create the initial ZZIK schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "albums",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("invite_code", sa.String(32), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "album_id",
            sa.String(36),
            sa.ForeignKey("albums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_key", sa.String(1024)),
        sa.Column("reference_indexed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "photos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "album_id",
            sa.String(36),
            sa.ForeignKey("albums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploader_member_id",
            sa.String(36),
            sa.ForeignKey("members.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("thumb_key", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_status", sa.String(16), nullable=False),
        sa.Column("analysis_error", sa.String(1000)),
        sa.Column("provider", sa.String(100)),
        sa.Column("mode", sa.String(100)),
        sa.Column("face_count", sa.Integer(), nullable=False),
        sa.Column("shot_type", sa.String(16), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("burst_group_id", sa.String(36)),
        sa.Column("best_score", sa.Float()),
        sa.Column("is_best", sa.Boolean(), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_photos_byte_size_nonnegative"),
        sa.CheckConstraint("face_count >= 0", name="ck_photos_face_count_nonnegative"),
    )
    op.create_index(
        "ix_photos_album_analysis_status",
        "photos",
        ["album_id", "analysis_status"],
    )
    op.create_index(
        "ix_photos_album_shot_type", "photos", ["album_id", "shot_type"]
    )
    op.create_table(
        "photo_members",
        sa.Column(
            "photo_id",
            sa.String(36),
            sa.ForeignKey("photos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("similarity", sa.Float()),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "similarity IS NULL OR (similarity >= 0 AND similarity <= 100)",
            name="ck_photo_members_similarity_range",
        ),
    )
    op.create_index("ix_photo_members_member_id", "photo_members", ["member_id"])
    op.create_table(
        "edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "photo_id",
            sa.String(36),
            sa.ForeignKey("photos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_member_id", sa.String(36), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("edits.id")),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("brightness", sa.Float(), nullable=False),
        sa.Column("saturation", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "brightness >= 0.5 AND brightness <= 1.5",
            name="ck_edits_brightness_range",
        ),
        sa.CheckConstraint(
            "saturation >= 0.0 AND saturation <= 2.0",
            name="ck_edits_saturation_range",
        ),
        sa.UniqueConstraint("photo_id", "number", name="uq_edits_photo_number"),
    )
    op.create_table(
        "approvals",
        sa.Column(
            "edit_id",
            sa.String(36),
            sa.ForeignKey("edits.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("approvals")
    op.drop_table("edits")
    op.drop_index("ix_photo_members_member_id", table_name="photo_members")
    op.drop_table("photo_members")
    op.drop_index("ix_photos_album_shot_type", table_name="photos")
    op.drop_index("ix_photos_album_analysis_status", table_name="photos")
    op.drop_table("photos")
    op.drop_table("members")
    op.drop_table("albums")
