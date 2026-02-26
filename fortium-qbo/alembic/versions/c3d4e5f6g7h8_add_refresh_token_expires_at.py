"""Add refresh_token_expires_at to qbo_companies

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add refresh_token_expires_at column to qbo_companies."""
    op.add_column(
        'qbo_companies',
        sa.Column('refresh_token_expires_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Remove refresh_token_expires_at column from qbo_companies."""
    op.drop_column('qbo_companies', 'refresh_token_expires_at')
