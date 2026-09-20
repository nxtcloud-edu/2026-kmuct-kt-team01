"""Store a perceptual hash per photo so near-duplicates can be grouped.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 기존 사진은 NULL 로 남는다. 해시가 없는 사진은 비교 대상에서 빠지고
    # 기존 촬영 시각 규칙으로만 묶인다.
    op.add_column("photos", sa.Column("phash", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("photos", "phash")
