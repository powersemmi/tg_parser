"""init

Revision ID: e766a37ae352
Revises:
Create Date: 2025-07-07 15:25:23.345611

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.sql.ddl import CreateSchema, DropSchema

# revision identifiers, used by Alembic.
revision: str = "e766a37ae352"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(CreateSchema("crawler", if_not_exists=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(DropSchema("crawler", if_exists=True, cascade=True))
