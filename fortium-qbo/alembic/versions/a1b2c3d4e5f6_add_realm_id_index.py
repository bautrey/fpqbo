"""Add index on qbo_companies.realm_id

Revision ID: a1b2c3d4e5f6
Revises: 20d4b90f8e32
Create Date: 2025-12-31

Per stakeholder feedback: Index on realm_id for performance on company lookup.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '20d4b90f8e32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique index on realm_id column."""
    op.create_index('ix_qbo_companies_realm_id', 'qbo_companies', ['realm_id'], unique=True)


def downgrade() -> None:
    """Remove realm_id index."""
    op.drop_index('ix_qbo_companies_realm_id', table_name='qbo_companies')
