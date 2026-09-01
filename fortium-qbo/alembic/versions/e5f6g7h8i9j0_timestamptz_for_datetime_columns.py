"""Convert every datetime column to timestamptz

Nine columns across four tables were `timestamp without time zone`: values
that are UTC by convention and unmarked in fact. Anything reading them back
got a naive datetime, so comparing one against a timezone-aware value raised
TypeError — which is what kept the whole codebase on the deprecated
`datetime.utcnow()` rather than being free to move.

`USING <col> AT TIME ZONE 'UTC'` is the load-bearing clause. Without it
Postgres reinterprets each existing value against the session TimeZone; with
it the stored instants are read as the UTC they always were. The session
TimeZone on this instance is in fact UTC, so both readings agree today —
the clause is there so the conversion stays correct if that ever changes,
and so the intent is legible rather than accidental.

Reversible. The downgrade converts back with the mirror clause, and since
every value is UTC on both sides the round trip is lossless.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-08-31

"""

from typing import Sequence, Union

from alembic import op

revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) for every timestamp column in the schema. Verified against
# information_schema on the live database rather than read off the models, so
# a column the models had drifted away from would still be caught.
#
# These are hardcoded and must stay hardcoded. The statements below build DDL
# by interpolation, which is safe only because nothing here comes from a
# caller or from the database. Anything that makes this list dynamic needs
# psycopg2.sql.Identifier rather than this pattern.
COLUMNS: list[tuple[str, str]] = [
    ("admin_users", "created_at"),
    ("admin_users", "last_login_at"),
    ("api_keys", "created_at"),
    ("api_keys", "last_used_at"),
    ("qbo_companies", "created_at"),
    ("qbo_companies", "last_refreshed_at"),
    ("qbo_companies", "refresh_token_expires_at"),
    ("qbo_companies", "token_expires_at"),
    ("request_log", "created_at"),
]


def upgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE timestamptz '
            f'USING "{column}" AT TIME ZONE \'UTC\''
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{column}" TYPE timestamp '
            f'USING "{column}" AT TIME ZONE \'UTC\''
        )
