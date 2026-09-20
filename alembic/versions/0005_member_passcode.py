"""Let members prove who they are with a per-album passcode so they can re-enter.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 이미 참여한 멤버는 NULL 로 남는다. 그 이름으로 처음 다시 들어오는 사람이
    # 비밀번호를 정하게 된다(api.join_album 참고).
    op.add_column("members", sa.Column("passcode_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("members", "passcode_hash")
