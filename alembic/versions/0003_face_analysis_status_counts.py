"""Persist unresolved face status counts for the frontend.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column("uncertain_face_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "photos",
        sa.Column("unregistered_face_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("photos", "unregistered_face_count")
    op.drop_column("photos", "uncertain_face_count")
