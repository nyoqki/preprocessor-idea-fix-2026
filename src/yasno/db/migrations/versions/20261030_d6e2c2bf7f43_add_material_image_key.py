from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e2c2bf7f43"
down_revision: str | None = "de52253236eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("image_key", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("materials", "image_key")
