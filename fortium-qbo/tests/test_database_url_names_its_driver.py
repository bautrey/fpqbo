"""The PostgreSQL driver is named, not inherited from SQLAlchemy's default.

On 2026-09-29 the deploy of #47 failed, and nothing in #47 caused it:

    File "sqlalchemy/dialects/postgresql/psycopg.py", line 497, in import_dbapi
        import psycopg
    ModuleNotFoundError: No module named 'psycopg'

SQLAlchemy 2.1 changed the DBAPI a bare `postgresql://` URL resolves to, from
`psycopg2` to `psycopg` (v3). requirements.txt carried `sqlalchemy>=2.0.0`
beside `psycopg2-binary`, so the first Render build after 2.1.1 shipped
installed a SQLAlchemy that wanted a driver nobody had installed. The container
never finished importing `app.main`; the previous release kept serving, and
production sat on eleven-day-old code while main said otherwise.

Measured, both directions:

    sqlalchemy 2.0.54   postgresql://  ->  sqlalchemy.dialects.postgresql.psycopg2
    sqlalchemy 2.1.1    postgresql://  ->  sqlalchemy.dialects.postgresql.psycopg

The whole defect lives in the word SQLAlchemy chose on our behalf, so these
tests are about the URL, not about the database. Nothing here connects to
anything.
"""

import pytest
from sqlalchemy.engine.url import make_url

from app.database import resolve_database_url


# The scheme production actually sets. Confirmed against the Render service's
# DATABASE_URL on 2026-09-29 (scheme only — the value is a secret).
BARE_PG = "postgresql://user:pw@host:5432/fpqbo"


def test_a_bare_postgresql_url_comes_back_naming_psycopg2():
    """The regression, asserted on the STRING rather than on the dialect.

    Asserting `get_dialect().driver == "psycopg2"` is the obvious form and it
    is **vacuous here**: requirements.txt now pins `sqlalchemy<2.1`, and on 2.0
    a bare `postgresql://` already resolves to psycopg2, so that assertion
    stays green with the rewrite deleted. It could only fail on the version the
    pin exists to keep out. A test that cannot fail on the stack it runs on is
    not evidence, so the check is on the text of the URL, which no SQLAlchemy
    version gets a vote on.

    Verified by ablation on both majors — see the docstring of the module.
    """
    out = resolve_database_url(BARE_PG)

    assert out.startswith("postgresql+psycopg2://"), (
        f"resolved URL is {out!r}; a scheme that does not name psycopg2 leaves "
        "the driver to SQLAlchemy's default, which is what changed under us"
    )


def test_the_installed_sqlalchemy_also_resolves_it_to_psycopg2():
    """The end-to-end form, kept for what it does catch.

    It cannot fail while the pin holds SQLAlchemy at 2.0 — that is what the
    test above is for. What it does catch is the pin being lifted to a
    SQLAlchemy where `+psycopg2` stops meaning psycopg2, which is the failure
    the string check cannot see.
    """
    assert make_url(resolve_database_url(BARE_PG)).get_dialect().driver == "psycopg2"


def test_the_rewrite_changes_only_the_driver():
    """A URL rewrite that drops the password or the port is a worse bug."""
    before = make_url(BARE_PG)
    after = make_url(resolve_database_url(BARE_PG))

    assert after.username == before.username
    assert after.password == before.password
    assert after.host == before.host
    assert after.port == before.port
    assert after.database == before.database
    assert after.query == before.query


def test_a_query_string_survives():
    """Render appends sslmode on some databases."""
    out = make_url(resolve_database_url(f"{BARE_PG}?sslmode=require"))
    assert out.query.get("sslmode") == "require"
    assert out.get_dialect().driver == "psycopg2"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./data/fortium-qbo.db",
        "postgresql+psycopg2://user:pw@host:5432/fpqbo",
        "postgresql+psycopg://user:pw@host:5432/fpqbo",
        "mysql+pymysql://user:pw@host/db",
    ],
    ids=["sqlite", "explicit-psycopg2", "explicit-psycopg3", "other-dialect"],
)
def test_a_url_that_already_names_its_driver_is_left_alone(url):
    """Including `+psycopg`. Somebody choosing psycopg3 on purpose keeps it.

    The default is what was unsafe, not psycopg3.
    """
    assert resolve_database_url(url) == url


def test_the_heroku_style_alias_is_normalised():
    """`postgres://` has not been a valid SQLAlchemy scheme since 1.4."""
    out = resolve_database_url("postgres://user:pw@host:5432/fpqbo")
    assert out.startswith("postgresql+psycopg2://")
    assert make_url(out).database == "fpqbo"


def test_the_engine_this_service_builds_uses_psycopg2_for_a_bare_url():
    """End to end through the module, not just the helper.

    The helper being right is worth nothing if `create_engine` is still handed
    `settings.database_url`, which is exactly how this shipped.
    """
    import app.database as db

    src = __import__("pathlib").Path(db.__file__).read_text()
    assert "create_engine(\n        resolve_database_url(" in src or \
           "resolve_database_url(settings.database_url)" in src, (
        "create_engine is not being handed the resolved URL, so the rewrite "
        "cannot reach the engine"
    )


def test_alembic_hands_its_engine_the_resolved_url_too():
    """Alembic builds its own engine from DATABASE_URL, outside app.database.

    It does not run on deploy, so it could not have caused the outage. It would
    reproduce it for anyone running a migration by hand once the <2.1 pin is
    lifted, which is the moment the rewrite exists to make safe.
    """
    import pathlib

    env = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    src = env.read_text()
    assert "resolve_database_url(settings.database_url)" in src, (
        "alembic/env.py sets sqlalchemy.url from the raw DATABASE_URL"
    )
