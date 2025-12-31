"""Add region column to qbo_companies

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add region column to qbo_companies with default 'US'."""
    op.add_column(
        'qbo_companies',
        sa.Column('region', sa.String(length=2), nullable=False, server_default='US')
    )


def downgrade() -> None:
    """Remove region column from qbo_companies."""
    op.drop_column('qbo_companies', 'region')
