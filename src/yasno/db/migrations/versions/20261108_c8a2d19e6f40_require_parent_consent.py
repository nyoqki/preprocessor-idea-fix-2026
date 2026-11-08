from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a2d19e6f40"
down_revision: str | None = "d6e2c2bf7f43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "requires_parent_consent", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "requires_parent_consent")
