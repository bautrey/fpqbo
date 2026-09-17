"""Add can_write column to api_keys

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-09-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, Sequence[str], None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_can_write() -> bool:
    """Whether api_keys already has the can_write column."""
    inspector = sa.inspect(op.get_bind())
    return any(
        col["name"] == "can_write"
        for col in inspector.get_columns("api_keys")
    )


def upgrade() -> None:
    """Add can_write to api_keys (default False = read-only).

    Idempotent for the same reason d4e5f6g7h8i9 is: the app's startup guard
    (app.database._ensure_additive_columns) may have already added this column
    on a deploy that ran before this migration, and alembic has no deploy hook
    here. Skip the add in that case so `alembic upgrade head` does not fail with
    DuplicateColumn on a guard-patched database.
    """
    if _has_can_write():
        return
    op.add_column(
        'api_keys',
        sa.Column(
            'can_write',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The other add-column migrations in this directory stop at server_default
    # and write no data. This one cannot: a default of false applied to the
    # existing rows would revoke write access from every key already in use —
    # the Payouts keys create bill payments and vendor credits today, and they
    # would start answering 403 the moment this ran.
    #
    # Active keys therefore keep exactly the access they have now, and the one
    # revoked key (id=1, "test") is deliberately left read-only so that
    # reactivating it later yields the safe key rather than the dangerous one.
    #
    # Tightening individual keys afterwards is a separate decision and there is
    # currently no evidence to make it on: request_log is empty because
    # log_request() has never had a caller, so nothing records which keys have
    # actually issued a write.
    op.execute("UPDATE api_keys SET can_write = true WHERE is_active = true")


def downgrade() -> None:
    """Remove can_write column from api_keys."""
    if _has_can_write():
        op.drop_column('api_keys', 'can_write')
