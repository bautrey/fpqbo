# TRD: Phase 1 - Core Infrastructure

**Issue:** [FOR-81](https://linear.app/fortiumpartners/issue/FOR-81/phase-1-core-infrastructure)
**Project:** fortium-qbo
**PRD:** [FOR-81 Phase 1 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
**Status:** Ready for Implementation
**Created:** 2025-12-17
**Version:** 1.2

---

## Execution Workflow

```bash
# Step 1: Implement all tasks in this TRD
/agent-os:implement-tasks docs/TRD/FOR-81-phase1-core-infrastructure-trd.md

# Step 2: Verify all verification gates pass (T1.0, T2.0, T3.0, T4.0, T5.0, T6.0)

# Step 3: Create git commit for Phase 1 completion
git add .
git commit -m "feat: implement Phase 1 core infrastructure for fortium-qbo

- Complete project directory structure with placeholders
- SQLAlchemy 2.0 models with relationships (4 tables)
- Alembic migrations with initial schema
- Pydantic settings with validation
- FastAPI application with health endpoint
- Requirements and documentation

Implements FOR-81"
```

---

## Technical Context

### Reference Patterns

This implementation follows proven patterns from `/Users/burke/projects/pipelinemgr/`:

| Component | Reference File | Key Patterns |
|-----------|----------------|--------------|
| **Models** | `app/models/company.py` | SQLAlchemy 2.0 `Mapped`, `mapped_column`, `relationship()` |
| **Models** | `app/models/deal.py` | Foreign keys, indexes, `TYPE_CHECKING` imports |
| **Database** | `app/database.py` | `DeclarativeBase`, session management via generator |
| **Config** | `app/config.py` | `pydantic_settings.BaseSettings`, `@lru_cache`, `.env` support |
| **FastAPI App** | `app/main.py` | `@asynccontextmanager` lifespan, static files, health endpoint |
| **Alembic** | `alembic/env.py` | Model imports, settings integration, metadata target |

### Technology Stack

- **FastAPI** 0.109.0+ - Web framework
- **SQLAlchemy** 2.0.0+ - ORM with typed mappings
- **Alembic** 1.13.0+ - Database migrations
- **Pydantic** 2.0.0+ - Settings and validation
- **Uvicorn** 0.27.0+ - ASGI server
- **SQLite** - Development database (production: PostgreSQL)

### Architecture Overview

```
fortium-qbo/
├── app/                    # Application code
│   ├── models/            # SQLAlchemy models (4 tables)
│   ├── routers/           # FastAPI route handlers (placeholders)
│   ├── services/          # Business logic (placeholders)
│   ├── templates/         # Jinja2 templates (placeholders)
│   ├── main.py            # FastAPI application
│   ├── config.py          # Pydantic settings
│   ├── database.py        # SQLAlchemy setup
│   └── dependencies.py    # Shared dependencies
├── alembic/               # Database migrations
├── static/                # CSS/JS assets (placeholders)
└── data/                  # SQLite database (gitignored)
```

---

## Master Task List

### Phase 1: Directory Structure & Scaffolding

**Goal:** Create complete project structure with placeholders for future phases

- [ ] **T1** - Create project directory structure
  - [ ] **T1.1** - Create core application directories
  - [ ] **T1.2** - Create placeholder directories for future phases
  - [ ] **T1.3** - Create Git configuration files
  - [ ] **T1.4** - Create environment configuration files
  - **Verification Gate:** T1.0 - Verify directory structure
  - **Git Checkpoint:** After T1.4 completion

### Phase 2: Configuration Management

**Goal:** Implement Pydantic settings with validation (required before database layer)

- [ ] **T2** - Implement configuration layer
  - [ ] **T2.1** - Implement config.py with Pydantic settings
  - **Verification Gate:** T2.0 - Verify settings load and validation
  - **Git Checkpoint:** After T2.1 completion

### Phase 3: Database Layer

**Goal:** Implement SQLAlchemy models with relationships and database setup

- [ ] **T3** - Implement database foundation
  - [ ] **T3.1** - Implement database.py with Base and session management
  - [ ] **T3.2** - Implement dependencies.py with get_db()
  - [ ] **T3.3** - Implement QboCompany model
  - [ ] **T3.4** - Implement ApiKey model
  - [ ] **T3.5** - Implement AdminUser model
  - [ ] **T3.6** - Implement RequestLog model
  - [ ] **T3.7** - Create models __init__.py with exports
  - **Verification Gate:** T3.0 - Verify models import and relationships
  - **Git Checkpoint:** After T3.7 completion

### Phase 4: Database Migrations

**Goal:** Set up Alembic with initial migration

- [ ] **T4** - Configure Alembic migrations
  - [ ] **T4.1** - Initialize Alembic configuration
  - [ ] **T4.2** - Configure alembic/env.py with model imports
  - [ ] **T4.3** - Create initial migration script
  - **Verification Gate:** T4.0 - Verify alembic upgrade head works
  - **Git Checkpoint:** After T4.3 completion

### Phase 5: FastAPI Application

**Goal:** Create FastAPI app with health endpoint and static file serving

- [ ] **T5** - Implement FastAPI application
  - [ ] **T5.1** - Implement app/main.py with lifespan and health endpoint
  - [ ] **T5.2** - Create placeholder router files
  - **Verification Gate:** T5.0 - Verify uvicorn starts and health endpoint works
  - **Git Checkpoint:** After T5.2 completion

### Phase 6: Dependencies & Documentation

**Goal:** Finalize requirements and project documentation

- [ ] **T6** - Complete dependencies and documentation
  - [ ] **T6.1** - Create requirements.txt
  - [ ] **T6.2** - Create README.md with setup instructions
  - **Verification Gate:** T6.0 - Verify pip install and documentation completeness

### Code Review Gate

- [ ] **CR1** - Code review checkpoint
  - [ ] All tasks T1-T6 completed
  - [ ] All verification gates passed
  - [ ] Git checkpoints completed
  - [ ] Code follows pipelinemgr patterns
  - [ ] No TODO or FIXME comments remain

---

## Detailed Task Specifications

### T1: Create Project Directory Structure

#### T1.1: Create Core Application Directories

**WHAT:** Create the core `app/` directory structure with all subdirectories
**HOW:** Use `mkdir -p` to create nested directories, create `__init__.py` files
**TOOL:** Bash

**File Operations:**
```bash
cd /Users/burke/projects/fpqbo
mkdir -p fortium-qbo/app/models
mkdir -p fortium-qbo/app/routers
mkdir -p fortium-qbo/app/services
mkdir -p fortium-qbo/app/templates

# Create __init__.py files
touch fortium-qbo/app/__init__.py
touch fortium-qbo/app/models/__init__.py
touch fortium-qbo/app/routers/__init__.py
touch fortium-qbo/app/services/__init__.py
```

**Success Criteria:**
- All directories exist
- All `__init__.py` files present

---

#### T1.2: Create Placeholder Directories for Future Phases

**WHAT:** Create static assets directories and data directory with .gitkeep files
**HOW:** Use `mkdir -p` and create .gitkeep placeholder files
**TOOL:** Bash

**File Operations:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
mkdir -p static/css
mkdir -p static/js
mkdir -p data
mkdir -p alembic/versions

# Create .gitkeep files for empty directories
touch static/css/.gitkeep
touch static/js/.gitkeep
touch app/templates/.gitkeep
```

**Success Criteria:**
- All static directories exist
- .gitkeep files prevent empty directory issues in git

---

#### T1.3: Create Git Configuration Files

**WHAT:** Create .gitignore file to exclude generated files, secrets, and database
**HOW:** Write .gitignore with standard Python and project-specific exclusions
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/.gitignore`

**Content:**
```gitignore
# Database
data/

# Python
venv/
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/
.eggs/

# Environment
.env
!.env.example

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Testing
.pytest_cache/
.coverage
htmlcov/

# Logs
*.log
```

**Success Criteria:**
- .gitignore excludes data/, venv/, .env
- .env.example is NOT excluded (note the !)

---

#### T1.4: Create Environment Configuration Files

**WHAT:** Create .env.example with all required and optional settings
**HOW:** Write .env.example with placeholder values and comments
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/.env.example`

**Content:**
```bash
# Application
APP_SECRET_KEY=your-secret-key-at-least-32-characters-long
SESSION_MAX_AGE_DAYS=30
DEBUG=false

# Google OAuth (Admin UI)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Google OAuth (Optional)
GOOGLE_ALLOWED_DOMAIN=fortiumpartners.com
INITIAL_ADMIN_EMAIL=admin@fortiumpartners.com

# QBO OAuth (Optional - for Phase 3+)
QBO_CLIENT_ID=
QBO_CLIENT_SECRET=

# Database
DATABASE_URL=sqlite:///./data/fortium-qbo.db

# Deployment
BASE_URL=http://localhost:8000
```

**Success Criteria:**
- All settings from PRD AC4 present
- Clear comments for required vs optional
- Placeholder values provided

---

#### T1.0: Verification Gate - Directory Structure

**WHAT:** Verify complete directory structure exists
**HOW:** Use find and grep to count directories, verify key files
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Verify directory count
find . -type d | grep -E "(models|routers|services|templates|static)" | wc -l
# Expected: 6 (models, routers, services, templates, static/css, static/js)

# Verify __init__.py files
find app -name "__init__.py" | wc -l
# Expected: 4 (app, models, routers, services)

# Verify .gitkeep files
find . -name ".gitkeep" | wc -l
# Expected: 3 (static/css, static/js, templates)

# Verify config files
ls -1 .gitignore .env.example
# Expected: both files exist
```

**Success Criteria:**
- All directory counts match expected values
- All configuration files present
- Structure matches PRD AC1

---

### T2: Implement Configuration Layer

#### T2.1: Implement config.py

**WHAT:** Create config.py with Pydantic settings following pipelinemgr pattern
**HOW:** Use pydantic_settings.BaseSettings with validation and .env support
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/config.py`

**Content:**
```python
"""Application configuration using Pydantic settings."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_secret_key: SecretStr = Field(min_length=32)
    session_max_age_days: int = 30
    debug: bool = False

    # Google OAuth (Admin UI) - Required
    google_client_id: str = Field(min_length=1)
    google_client_secret: SecretStr = Field(min_length=1)
    google_allowed_domain: str = "fortiumpartners.com"
    initial_admin_email: str | None = None

    # QBO OAuth (Optional - for Phase 3+)
    qbo_client_id: str | None = None
    qbo_client_secret: SecretStr | None = None

    # Database
    database_url: str = "sqlite:///./data/fortium-qbo.db"

    # Deployment
    base_url: str = "http://localhost:8000"

    @property
    def session_max_age_seconds(self) -> int:
        """Session max age in seconds for cookie configuration."""
        return self.session_max_age_days * 24 * 60 * 60

    @field_validator("app_secret_key")
    @classmethod
    def validate_secret_key_length(cls, v: SecretStr) -> SecretStr:
        """Ensure app_secret_key is at least 32 characters."""
        if len(v.get_secret_value()) < 32:
            raise ValueError("app_secret_key must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
```

**Success Criteria:**
- All settings from PRD AC4 present
- Required fields validated (google_client_id, google_client_secret, app_secret_key)
- app_secret_key minimum 32 characters enforced
- .env file support configured
- Settings cached via @lru_cache

---

#### T2.0: Verification Gate - Settings Load and Validation

**WHAT:** Verify settings load from .env and validation works
**HOW:** Test with valid .env and test validation errors
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Create test .env for imports
cat > .env << 'EOF'
APP_SECRET_KEY=test-secret-key-at-least-32-chars-long-for-testing
GOOGLE_CLIENT_ID=test-client-id
GOOGLE_CLIENT_SECRET=test-secret
DATABASE_URL=sqlite:///./data/fortium-qbo.db
EOF

# Test valid settings load
python3 << 'PYEOF'
from app.config import settings

assert settings.debug == False
assert settings.database_url.startswith("sqlite")
assert settings.google_allowed_domain == "fortiumpartners.com"
assert len(settings.app_secret_key.get_secret_value()) >= 32
assert settings.session_max_age_days == 30
assert settings.session_max_age_seconds == 30 * 24 * 60 * 60

print("✓ Settings loaded successfully from .env")
print("✓ All validation passed")
print("✓ Computed properties work (session_max_age_seconds)")
PYEOF
```

**Success Criteria:**
- Settings load from .env without errors
- Validation enforces minimum secret key length
- All required fields validated
- Computed properties work correctly

---

### T3: Implement Database Foundation

#### T3.1: Implement database.py

**WHAT:** Create database.py with Base class, engine, and session management
**HOW:** Follow pipelinemgr/app/database.py pattern with SQLAlchemy 2.0
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/database.py`

**Content:**
```python
"""Database configuration with SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def _get_engine_kwargs() -> dict:
    """Get database engine kwargs based on database URL."""
    if settings.database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


# Create engine
engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    **_get_engine_kwargs(),
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

**Success Criteria:**
- DeclarativeBase defined
- Engine created with conditional kwargs (sqlite vs postgres)
- Session factory configured
- get_db() generator follows dependency injection pattern

---

#### T3.2: Implement dependencies.py

**WHAT:** Create dependencies.py that re-exports get_db for FastAPI
**HOW:** Import and re-export get_db from database module
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/dependencies.py`

**Content:**
```python
"""Shared dependencies for FastAPI dependency injection."""

from app.database import get_db

__all__ = ["get_db"]
```

**Success Criteria:**
- get_db available from app.dependencies
- Clean separation of concerns

---

#### T3.3: Implement QboCompany Model

**WHAT:** Create qbo_company.py with SQLAlchemy 2.0 typed model
**HOW:** Follow pipelinemgr/app/models/company.py pattern with Mapped and relationship
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/models/qbo_company.py`

**Content:**
```python
"""QBO Company model for QuickBooks Online company credentials."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class QboCompany(Base):
    """
    QboCompany model representing QuickBooks Online company credentials.

    Stores OAuth tokens and company metadata for QBO API access.
    Related to ApiKey (one-to-many).
    """

    __tablename__ = "qbo_companies"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Company identification
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        String(10), unique=True, nullable=False, index=True
    )
    realm_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # OAuth tokens
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    token_status: Mapped[str] = mapped_column(String(20), default="active")
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey",
        back_populates="company",
        foreign_keys="ApiKey.company_id",
    )

    # Additional indexes
    __table_args__ = (Index("ix_qbo_companies_code", "code"),)

    def __repr__(self) -> str:
        return f"<QboCompany(id={self.id}, code={self.code}, name={self.name})>"
```

**Success Criteria:**
- All fields from PRD AC2 present with correct types
- `code` field unique and indexed
- Relationship to ApiKey defined with back_populates
- TYPE_CHECKING import pattern used

---

#### T3.4: Implement ApiKey Model

**WHAT:** Create api_key.py with foreign key to QboCompany and RequestLog relationship
**HOW:** Follow pipelinemgr/app/models/deal.py pattern with ForeignKey and multiple relationships
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/models/api_key.py`

**Content:**
```python
"""API Key model for gateway authentication."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.qbo_company import QboCompany
    from app.models.request_log import RequestLog


class ApiKey(Base):
    """
    ApiKey model for API gateway authentication.

    Stores hashed API keys for n8n workflow authentication.
    Related to QboCompany (many-to-one) and RequestLog (one-to-many).
    """

    __tablename__ = "api_keys"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Key data (hashed)
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Foreign key to QboCompany
    company_id: Mapped[int] = mapped_column(
        ForeignKey("qbo_companies.id"), nullable=False
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    company: Mapped["QboCompany"] = relationship(
        "QboCompany",
        foreign_keys=[company_id],
        back_populates="api_keys",
    )
    request_logs: Mapped[list["RequestLog"]] = relationship(
        "RequestLog",
        back_populates="api_key",
        cascade="all, delete-orphan",
    )

    # Additional indexes
    __table_args__ = (
        Index("ix_api_keys_key_hash", "key_hash"),
        Index("ix_api_keys_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, name={self.name})>"
```

**Success Criteria:**
- All fields from PRD AC2 present
- Foreign key to qbo_companies defined
- Both relationships (company, request_logs) configured
- Indexes on key_hash and company_id

---

#### T3.5: Implement AdminUser Model

**WHAT:** Create admin_user.py with standalone model (no relationships)
**HOW:** Follow company.py pattern but simpler - no relationships
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/models/admin_user.py`

**Content:**
```python
"""Admin User model for Google OAuth authentication."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AdminUser(Base):
    """
    AdminUser model for Google OAuth authenticated administrators.

    Stores admin user information for access to admin UI.
    No relationships - standalone table.
    """

    __tablename__ = "admin_users"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User identification
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    # Permissions
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Additional indexes
    __table_args__ = (Index("ix_admin_users_email", "email"),)

    def __repr__(self) -> str:
        return f"<AdminUser(id={self.id}, email={self.email})>"
```

**Success Criteria:**
- All fields from PRD AC2 present
- Email unique and indexed
- No relationships (standalone table)
- Simple model structure

---

#### T3.6: Implement RequestLog Model

**WHAT:** Create request_log.py with nullable foreign key to ApiKey
**HOW:** Follow pattern but with nullable ForeignKey for unauthenticated requests
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/models/request_log.py`

**Content:**
```python
"""Request Log model for API gateway audit trail."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class RequestLog(Base):
    """
    RequestLog model for API gateway request audit trail.

    Logs all requests to the gateway for monitoring and debugging.
    Related to ApiKey (many-to-one, nullable for unauthenticated requests).
    """

    __tablename__ = "request_log"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign key to ApiKey (nullable - may not have valid API key)
    api_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("api_keys.id"), nullable=True
    )

    # Request details
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamp (indexed for time-based queries)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, index=True
    )

    # Relationships
    api_key: Mapped[Optional["ApiKey"]] = relationship(
        "ApiKey",
        foreign_keys=[api_key_id],
        back_populates="request_logs",
    )

    # Additional indexes
    __table_args__ = (Index("ix_request_log_created_at", "created_at"),)

    def __repr__(self) -> str:
        return f"<RequestLog(id={self.id}, endpoint={self.endpoint}, status={self.status_code})>"
```

**Success Criteria:**
- All fields from PRD AC2 present
- api_key_id nullable (for unauthenticated requests)
- Relationship to ApiKey nullable
- created_at indexed for time queries

---

#### T3.7: Create Models __init__.py

**WHAT:** Create models/__init__.py that exports all models
**HOW:** Import and re-export all model classes for clean imports
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/models/__init__.py`

**Content:**
```python
"""SQLAlchemy models for fortium-qbo."""

from app.models.admin_user import AdminUser
from app.models.api_key import ApiKey
from app.models.qbo_company import QboCompany
from app.models.request_log import RequestLog

__all__ = [
    "AdminUser",
    "ApiKey",
    "QboCompany",
    "RequestLog",
]
```

**Success Criteria:**
- All models importable via `from app.models import QboCompany`
- Clean public API with __all__

---

#### T3.0: Verification Gate - Models Import and Relationship Traversal

**WHAT:** Verify all models import and relationships actually work (not just exist)
**HOW:** Create objects, link them via foreign keys, and traverse relationships both directions
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Ensure test .env exists
cat > .env << 'EOF'
APP_SECRET_KEY=test-secret-key-at-least-32-chars-long-for-testing
GOOGLE_CLIENT_ID=test-client-id
GOOGLE_CLIENT_SECRET=test-secret
DATABASE_URL=sqlite:///./data/fortium-qbo.db
EOF

# Ensure data directory exists
mkdir -p data

# Test model imports and table registration
python3 << 'PYEOF'
from app.models import QboCompany, ApiKey, AdminUser, RequestLog
from app.database import Base

# Verify all models registered
tables = Base.metadata.tables
assert len(tables) == 4, f"Expected 4 tables, got {len(tables)}"
assert "qbo_companies" in tables
assert "api_keys" in tables
assert "admin_users" in tables
assert "request_log" in tables

print("✓ All models imported successfully")
print("✓ All 4 tables registered with Base.metadata")
PYEOF

# Test actual relationship traversal (from PRD AC2)
python3 << 'PYEOF'
from app.database import SessionLocal, Base, engine
from app.models import QboCompany, ApiKey

# Create tables for test
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Create test company
company = QboCompany(name="Test", code="test", realm_id="123")
db.add(company)
db.commit()

# Create API key linked to company
api_key = ApiKey(
    key_hash="abc123",
    key_prefix="ftm_test",
    name="Test Key",
    company_id=company.id
)
db.add(api_key)
db.commit()

# Refresh to load relationships
db.refresh(company)

# Verify forward traversal: company -> api_keys
assert len(company.api_keys) == 1, f"Expected 1 api_key, got {len(company.api_keys)}"
assert company.api_keys[0].name == "Test Key"
print("✓ Forward traversal: company.api_keys works")

# Verify reverse traversal: api_key -> company
assert api_key.company.code == "test"
print("✓ Reverse traversal: api_key.company works")

# Cleanup
db.rollback()
db.close()

print("✓ All relationship traversal tests passed")
PYEOF
```

**Success Criteria:**
- All models import without errors
- 4 tables registered with Base.metadata
- Forward relationship traversal works (company → api_keys)
- Reverse relationship traversal works (api_key → company)
- Script outputs all success messages

---

### T4: Configure Alembic Migrations

#### T4.1: Initialize Alembic Configuration

**WHAT:** Run alembic init and configure alembic.ini
**HOW:** Use alembic init command, then edit alembic.ini to use environment variable
**TOOL:** Bash

**Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Initialize Alembic
alembic init alembic

# Update alembic.ini to use environment variable
# Remove the hardcoded sqlalchemy.url line
sed -i.bak '/^sqlalchemy.url = /d' alembic.ini

# Add comment about environment variable
cat >> alembic.ini << 'EOF'

# SQLAlchemy URL loaded from environment via alembic/env.py
# See app/config.py for DATABASE_URL configuration
EOF
```

**Success Criteria:**
- alembic/ directory created with env.py and script.py.mako
- alembic.ini created
- sqlalchemy.url removed (loaded from env instead)

---

#### T4.2: Configure alembic/env.py

**WHAT:** Update alembic/env.py to import models and use settings for database URL
**HOW:** Follow pipelinemgr/alembic/env.py pattern
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/alembic/env.py`

**Changes:**
1. Add imports for settings, Base, and all models
2. Set sqlalchemy.url from settings
3. Set target_metadata from Base.metadata

**Read, then edit to match this structure:**
```python
"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base

# Import all models to register with Base.metadata
from app.models import (  # noqa: F401
    AdminUser,
    ApiKey,
    QboCompany,
    RequestLog,
)

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set SQLAlchemy URL from settings
config.set_main_option("sqlalchemy.url", settings.database_url)

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Success Criteria:**
- All models imported for autogenerate support
- settings.database_url used for connection
- Base.metadata set as target_metadata

---

#### T4.3: Create Initial Migration Script

**WHAT:** Generate initial migration with all 4 tables
**HOW:** Use alembic revision --autogenerate
**TOOL:** Bash

**Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Generate initial migration
alembic revision --autogenerate -m "Initial schema: qbo_companies, api_keys, admin_users, request_log"

# List migration to verify
ls -la alembic/versions/
```

**Success Criteria:**
- Migration file created in alembic/versions/
- Migration creates all 4 tables
- Foreign keys and indexes included

---

#### T4.0: Verification Gate - Alembic Upgrade Works

**WHAT:** Verify alembic upgrade head creates all tables successfully
**HOW:** Run alembic upgrade head and verify database schema
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Run migrations
alembic upgrade head

# Verify tables exist
sqlite3 data/fortium-qbo.db ".tables"
# Expected output: admin_users  api_keys  qbo_companies  request_log

# Verify foreign keys
sqlite3 data/fortium-qbo.db ".schema api_keys" | grep -c "FOREIGN KEY"
# Expected: 1

# Verify indexes
sqlite3 data/fortium-qbo.db ".schema qbo_companies" | grep -c "CREATE INDEX"
# Expected: 1 (ix_qbo_companies_code)

echo "✓ Alembic upgrade successful"
echo "✓ All 4 tables created"
echo "✓ Foreign keys configured"
echo "✓ Indexes created"
```

**Success Criteria:**
- alembic upgrade head completes without errors
- All 4 tables exist in database
- Foreign keys created
- Indexes created

---

### T5: Implement FastAPI Application

#### T5.1: Implement app/main.py

**WHAT:** Create FastAPI app with lifespan, health endpoint, and static file serving
**HOW:** Follow pipelinemgr/app/main.py pattern
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/main.py`

**Content:**
```python
"""fortium-qbo - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown events.

    Startup:
    - Log application start
    - Placeholder for future initialization (Phase 2+)

    Shutdown:
    - Log application shutdown
    - Placeholder for future cleanup (Phase 2+)
    """
    # Startup
    logger.info("fortium-qbo starting up...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")

    yield

    # Shutdown
    logger.info("fortium-qbo shutting down...")


app = FastAPI(
    title="fortium-qbo",
    description="QuickBooks Online API Gateway",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}
```

**Success Criteria:**
- FastAPI app created with metadata
- Lifespan context manager for startup/shutdown
- Health endpoint at /health
- Static files mounted at /static
- Docs hidden unless debug=True

---

#### T5.2: Create Placeholder Router Files

**WHAT:** Create placeholder __init__.py files in routers and services
**HOW:** Write empty __init__.py files with comments
**TOOL:** Write

**File Path 1:** `/Users/burke/projects/fpqbo/fortium-qbo/app/routers/__init__.py`

**Content:**
```python
"""API routers for fortium-qbo.

Phase 2+:
- auth.py - Google OAuth admin authentication
- admin.py - Admin UI routes

Phase 3+:
- qbo_auth.py - QBO OAuth token management

Phase 4+:
- api_keys.py - API key management

Phase 5+:
- qbo_gateway.py - QBO entity endpoints (proxy)
"""
```

**File Path 2:** `/Users/burke/projects/fpqbo/fortium-qbo/app/services/__init__.py`

**Content:**
```python
"""Business logic services for fortium-qbo.

Phase 3+:
- qbo_client.py - QBO API client wrapper
- token_manager.py - Token refresh service

Phase 4+:
- api_key_service.py - API key generation and validation

Phase 5+:
- qbo_proxy.py - QBO request proxying
"""
```

**Success Criteria:**
- Placeholder files document future phases
- Clear separation of concerns established

---

#### T5.0: Verification Gate - Uvicorn Starts and Health Endpoint Works

**WHAT:** Verify uvicorn starts FastAPI app and health endpoint returns 200
**HOW:** Start uvicorn in background, test health endpoint, kill server
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Start uvicorn in background
DEBUG=true uvicorn app.main:app --host 0.0.0.0 --port 8765 &
UVICORN_PID=$!

# Wait for server to start
sleep 3

# Test health endpoint
HEALTH_RESPONSE=$(curl -s http://localhost:8765/health)
echo "Health response: $HEALTH_RESPONSE"

# Verify response
if echo "$HEALTH_RESPONSE" | grep -q '"status":"healthy"'; then
    echo "✓ Health endpoint returned correct response"
else
    echo "✗ Health endpoint failed"
    kill $UVICORN_PID
    exit 1
fi

# Test static files endpoint (should return 404 for non-existent file, but mount works)
STATIC_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/static/test.txt)
if [ "$STATIC_RESPONSE" = "404" ]; then
    echo "✓ Static files mount working (404 for non-existent file)"
else
    echo "✗ Static files mount failed"
fi

# Test docs endpoint when debug=true
DOCS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/docs)
if [ "$DOCS_RESPONSE" = "200" ]; then
    echo "✓ API docs accessible when DEBUG=true"
else
    echo "✗ API docs not accessible"
fi

# Kill uvicorn
kill $UVICORN_PID
wait $UVICORN_PID 2>/dev/null

echo "✓ Uvicorn started successfully"
echo "✓ All endpoints working"
```

**Success Criteria:**
- Uvicorn starts without errors
- /health returns {"status":"healthy"}
- /static mount works
- /docs accessible when debug=true

---

### T6: Complete Dependencies and Documentation

#### T6.1: Create requirements.txt

**WHAT:** Create requirements.txt with all dependencies from PRD AC6
**HOW:** Write requirements.txt with minimum versions
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/requirements.txt`

**Content:**
```
# Core
fastapi>=0.109.0
uvicorn[standard]>=0.27.0

# Database
sqlalchemy>=2.0.0
alembic>=1.13.0

# Configuration
pydantic>=2.0.0
pydantic-settings>=2.0.0

# Web
python-multipart>=0.0.6
jinja2>=3.1.0
itsdangerous>=2.1.0

# Future phases (included now to lock versions)
httpx>=0.26.0
authlib>=1.3.0
python-quickbooks>=0.9.0
```

**Success Criteria:**
- All dependencies from PRD AC6 present
- Minimum versions specified
- Comments for clarity

---

#### T6.2: Create README.md

**WHAT:** Create README.md with setup instructions following PRD AC9
**HOW:** Write comprehensive README with quick start, structure, links
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/README.md`

**Content:**
```markdown
# fortium-qbo

QuickBooks Online API Gateway for Fortium Partners workflows.

## Overview

fortium-qbo is a FastAPI-based gateway that provides:
- **Admin UI** - Google OAuth authenticated admin interface for token management
- **API Gateway** - API key authenticated proxy to QuickBooks Online API
- **Token Management** - Automatic OAuth token refresh for QBO credentials

Built for n8n workflow integration with secure credential management.

## Quick Start

### Prerequisites

- Python 3.11+
- QuickBooks Online developer account
- Google OAuth credentials (for admin UI)

### Installation

```bash
# Navigate to project directory
cd /Users/burke/projects/fpqbo/fortium-qbo

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see Configuration section)

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/health to verify the server is running.

When `DEBUG=true`, API docs are available at http://localhost:8000/docs

### Configuration

Copy `.env.example` to `.env` and configure the following required settings:

```bash
# Application (Required)
APP_SECRET_KEY=your-secret-key-at-least-32-characters-long

# Google OAuth (Required - for admin UI)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# QBO OAuth (Optional - configure in Phase 3)
QBO_CLIENT_ID=your-qbo-client-id
QBO_CLIENT_SECRET=your-qbo-client-secret

# Database (Optional - defaults to SQLite)
DATABASE_URL=sqlite:///./data/fortium-qbo.db

# Deployment (Optional)
BASE_URL=http://localhost:8000
```

## Project Structure

```
fortium-qbo/
├── app/
│   ├── models/              # SQLAlchemy models (4 tables)
│   │   ├── qbo_company.py   # QBO company credentials
│   │   ├── api_key.py       # API keys for n8n
│   │   ├── admin_user.py    # Admin users (Google OAuth)
│   │   └── request_log.py   # Request audit trail
│   ├── routers/             # FastAPI route handlers (Phase 2+)
│   ├── services/            # Business logic (Phase 3+)
│   ├── templates/           # Jinja2 templates (Phase 2+)
│   ├── main.py              # FastAPI application
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy setup
│   └── dependencies.py      # Shared dependencies
├── alembic/                 # Database migrations
├── static/                  # CSS/JS assets (Phase 2+)
├── data/                    # SQLite database (gitignored)
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
└── README.md                # This file
```

## Database

### Schema

The database consists of 4 tables:

1. **qbo_companies** - QuickBooks Online company credentials and OAuth tokens
2. **api_keys** - API keys for n8n workflow authentication (linked to companies)
3. **admin_users** - Admin users authenticated via Google OAuth
4. **request_log** - Audit trail of all API requests

### Migrations

```bash
# Create new migration after model changes
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

## Development

### Running Tests

```bash
# Unit tests (Phase 2+)
pytest tests/

# Coverage report (Phase 2+)
pytest --cov=app tests/
```

### Code Quality

```bash
# Format code
black app/

# Lint
ruff check app/

# Type checking
mypy app/
```

## Deployment

See [Design Document](/Users/burke/projects/fpqbo/docs/plans/2025-12-17-fortium-qbo-design.md) for deployment instructions.

Production deployment targets:
- **Platform:** Render
- **Database:** PostgreSQL (via Render)
- **Domain:** fortium-qbo.onrender.com

## Phase Roadmap

- ✅ **Phase 1:** Core Infrastructure (this phase)
- ⬜ **Phase 2:** Admin UI - Google OAuth authentication
- ⬜ **Phase 3:** QBO OAuth - Token management and refresh
- ⬜ **Phase 4:** API Gateway - API key authentication
- ⬜ **Phase 5:** QBO Proxy - Entity endpoints
- ⬜ **Phase 6:** Deployment - Render production deployment

## Documentation

- [Design Document](/Users/burke/projects/fpqbo/docs/plans/2025-12-17-fortium-qbo-design.md)
- [PRD: Phase 1](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
- [Linear Issue FOR-81](https://linear.app/fortiumpartners/issue/FOR-81/phase-1-core-infrastructure)

## License

Proprietary - Fortium Partners
```

**Success Criteria:**
- All sections from PRD AC9 present
- Quick start instructions complete
- Project structure documented
- Links to design documents

---

#### T6.0: Verification Gate - Pip Install and Documentation Completeness

**WHAT:** Verify pip install works and documentation is complete
**HOW:** Create fresh venv, install dependencies, verify imports
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Create fresh virtual environment
rm -rf venv_test
python3 -m venv venv_test
source venv_test/bin/activate

# Install requirements
pip install -r requirements.txt

# Verify imports work
python3 << 'PYEOF'
# Test core imports
from fastapi import FastAPI
from sqlalchemy import create_engine
from alembic import context
from pydantic_settings import BaseSettings

# Test app imports (with test .env)
import os
os.environ["APP_SECRET_KEY"] = "test-key-at-least-32-characters-long"
os.environ["GOOGLE_CLIENT_ID"] = "test"
os.environ["GOOGLE_CLIENT_SECRET"] = "test"

from app.main import app
from app.models import QboCompany, ApiKey, AdminUser, RequestLog
from app.config import settings

print("✓ All dependencies installed successfully")
print("✓ All app imports work")
PYEOF

# Cleanup
deactivate
rm -rf venv_test

# Verify README has key sections
grep -q "Quick Start" README.md && echo "✓ README has Quick Start section"
grep -q "Project Structure" README.md && echo "✓ README has Project Structure section"
grep -q "Database" README.md && echo "✓ README has Database section"
grep -q "fortium-qbo-design.md" README.md && echo "✓ README links to design doc"
```

**Success Criteria:**
- pip install completes without errors
- All imports work in fresh environment
- README has all required sections
- Documentation links valid

---

## Code Review Checklist

### CR1: Code Review Checkpoint

**Purpose:** Ensure all Phase 1 tasks meet quality standards before git commit

#### Completeness
- [ ] All tasks T1-T6 completed with checkboxes marked
- [ ] All verification gates (T1.0, T2.0, T3.0, T4.0, T5.0, T6.0) passed
- [ ] All git checkpoints identified for manual commits

#### Code Quality
- [ ] All files follow pipelinemgr reference patterns
- [ ] SQLAlchemy 2.0 `Mapped` and `mapped_column` syntax used
- [ ] Type hints present on all model fields
- [ ] Docstrings present on all classes and functions
- [ ] No TODO or FIXME comments remain

#### Database
- [ ] All 4 models implemented with correct fields
- [ ] Relationships configured with `back_populates`
- [ ] Foreign keys defined with proper constraints
- [ ] Indexes created on: code, key_hash, email, created_at
- [ ] Migration creates all tables successfully

#### Configuration
- [ ] All required settings validated (app_secret_key, google_client_id, google_client_secret)
- [ ] .env.example has all settings with placeholders
- [ ] .gitignore excludes data/, venv/, .env
- [ ] Settings cached via @lru_cache

#### FastAPI
- [ ] Lifespan context manager implemented
- [ ] Health endpoint returns {"status":"healthy"}
- [ ] Static files mounted at /static
- [ ] Docs hidden unless debug=True
- [ ] No router implementations yet (placeholders only)

#### Documentation
- [ ] README has quick start, structure, links
- [ ] All file paths in README are absolute
- [ ] requirements.txt has all dependencies with versions
- [ ] Comments explain future phase placeholders

#### Testing
- [ ] Can import all models: `from app.models import QboCompany, ApiKey, AdminUser, RequestLog`
- [ ] Can run: `alembic upgrade head` without errors
- [ ] Can run: `uvicorn app.main:app` without errors
- [ ] Can curl: `http://localhost:8000/health` → 200 OK
- [ ] Relationship traversal works (see PRD AC2 test)

---

## Success Criteria Summary

Phase 1 is complete when:

1. **Directory Structure** - All directories and placeholders exist (AC1)
2. **Models** - All 4 models with relationships implemented (AC2)
3. **Migrations** - Alembic configured and initial migration works (AC3)
4. **Configuration** - Pydantic settings with validation (AC4)
5. **FastAPI** - App with health endpoint and static files (AC5)
6. **Dependencies** - requirements.txt and pip install works (AC6)
7. **Git** - .gitignore configured correctly (AC7)
8. **Environment** - .env.example with all settings (AC8)
9. **Documentation** - README with setup instructions (AC9)

All verification gates must pass, and code review checklist complete.

---

## Appendix

### Git Checkpoints

Recommended git commits after each major phase:

```bash
# After T1.4 - Directory structure complete
git add .
git commit -m "chore: create fortium-qbo directory structure and config files"

# After T2.7 - Database models complete
git add app/
git commit -m "feat: implement SQLAlchemy models with relationships"

# After T4.3 - Alembic migrations work
git add alembic/
git commit -m "feat: configure Alembic with initial migration"

# After T5.2 - FastAPI app works
git add app/main.py app/routers/ app/services/
git commit -m "feat: implement FastAPI app with health endpoint"

# Final commit after all verification gates pass
git add .
git commit -m "feat: complete Phase 1 core infrastructure for fortium-qbo

- Complete project directory structure with placeholders
- SQLAlchemy 2.0 models with relationships (4 tables)
- Alembic migrations with initial schema
- Pydantic settings with validation
- FastAPI application with health endpoint
- Requirements and documentation

Implements FOR-81"
```

### Related Documents

- [PRD: Phase 1](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
- [Design Document](/Users/burke/projects/fpqbo/docs/plans/2025-12-17-fortium-qbo-design.md)
- [Linear Issue FOR-81](https://linear.app/fortiumpartners/issue/FOR-81/phase-1-core-infrastructure)

### Dependencies for Future Phases

Phase 2 (Admin UI) requires:
- T1 (directory structure with templates/)
- T2 (google_client_id, google_client_secret settings)
- T3 (AdminUser model)
- T5 (FastAPI app with lifespan)

Phase 3 (QBO OAuth) requires:
- T1 (directory structure with services/)
- T2 (qbo_client_id, qbo_client_secret settings)
- T3 (QboCompany model)
- T4 (database migrations)

Phase 4 (API Gateway) requires:
- T3 (ApiKey and RequestLog models)
- T5 (FastAPI app)

All subsequent phases depend on Phase 1 completion.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-17 | Initial TRD created by tech-lead-orchestrator |
| 1.1 | 2025-12-17 | Reordered tasks: T2 (Configuration) now before T3 (Database) to satisfy import dependency |
| 1.2 | 2025-12-17 | T3.0 verification gate now uses actual relationship traversal test (from PRD AC2) instead of weak hasattr checks |
