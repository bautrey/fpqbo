"""Add is_sandbox column to qbo_companies

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-06-27 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_is_sandbox() -> bool:
    """Whether qbo_companies already has the is_sandbox column."""
    inspector = sa.inspect(op.get_bind())
    return any(
        col["name"] == "is_sandbox"
        for col in inspector.get_columns("qbo_companies")
    )


def upgrade() -> None:
    """Add is_sandbox column to qbo_companies (default False = production).

    Idempotent: the app's startup guard (app.database._ensure_additive_columns)
    may have already added this column on a deploy that ran before this
    migration. Skip the add in that case so `alembic upgrade head` does not
    fail with DuplicateColumn on a guard-patched database.
    """
    if _has_is_sandbox():
        return
    op.add_column(
        'qbo_companies',
        sa.Column(
            'is_sandbox',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Remove is_sandbox column from qbo_companies."""
    if _has_is_sandbox():
        op.drop_column('qbo_companies', 'is_sandbox')
