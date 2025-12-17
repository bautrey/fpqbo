# PRD: Phase 1 - Core Infrastructure

**Issue:** [FOR-81](https://linear.app/fortiumpartners/issue/FOR-81/phase-1-core-infrastructure)
**Project:** fortium-qbo
**Date:** 2025-12-17
**Status:** Ready for TRD
**Version:** 1.2

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2 | 2025-12-17 | Added relationship traversal test per QA review |
| 1.1 | 2025-12-17 | Added placeholder directories, model relationships, clarified required config |
| 1.0 | 2025-12-17 | Initial PRD creation |

---

## Product Summary

### Problem Statement

The fortium-qbo project requires a solid foundation before any features can be built. Currently:
- No project structure exists in `fpqbo/fortium-qbo/`
- No database models or migrations are defined
- No configuration management is in place
- No FastAPI application scaffold exists

Without this foundation, subsequent phases (authentication, token management, API gateway) cannot proceed.

### Solution

Create the core infrastructure layer consisting of:
1. **Project scaffolding** - Complete directory structure with placeholders for future phases
2. **SQLAlchemy models** - Four core tables with relationships: `qbo_companies`, `api_keys`, `admin_users`, `request_log`
3. **Alembic migrations** - Database versioning and migration support
4. **Pydantic settings** - Environment-based configuration (all credentials required)
5. **FastAPI application** - Basic app with lifespan, health endpoint, static file serving

### Value Proposition

This phase establishes:
- **Consistency** - Follows proven patterns from pipelinemgr
- **Maintainability** - Proper separation of concerns, typed models with relationships
- **Extensibility** - Clean architecture with placeholder directories for subsequent phases
- **Testability** - Isolated components that can be unit tested

---

## User Analysis

### Primary Users

| User Type | Description | Needs |
|-----------|-------------|-------|
| **Developer (Burke)** | Implements subsequent phases | Clean, well-organized codebase following familiar patterns |
| **CI/CD Pipeline** | Runs tests, deploys to Render | Working health endpoint, proper requirements.txt |
| **Future Maintainers** | May need to modify or extend | Clear structure, documented patterns |

### User Personas

#### Burke (Primary Developer)
- **Role:** Solo developer implementing fortium-qbo
- **Context:** Familiar with pipelinemgr patterns (FastAPI + SQLAlchemy + Pydantic)
- **Pain Points:** Time wasted on boilerplate, inconsistent patterns across projects
- **Goals:** Get foundation in place quickly so real features can begin

### Pain Points Addressed

1. **No existing structure** → Complete project scaffolding with placeholders
2. **No database layer** → SQLAlchemy models with relationships + Alembic migrations
3. **No configuration** → Pydantic settings with .env support
4. **No entry point** → FastAPI app with lifespan management

---

## Goals & Non-Goals

### Goals

| Goal | Success Metric |
|------|----------------|
| Create complete directory structure | All directories from design doc exist (including placeholders) |
| Implement SQLAlchemy models | 4 models with relationships matching schema in design doc |
| Set up Alembic migrations | Initial migration creates all tables |
| Configure Pydantic settings | All env vars from design doc supported and validated |
| Create FastAPI application | `GET /health` returns 200 |

### Non-Goals (Out of Scope for Phase 1)

- Google OAuth authentication implementation (Phase 2)
- QBO OAuth token management (Phase 3)
- API key validation middleware (Phase 4)
- QBO entity endpoints (Phase 5)
- Deployment to Render (Phase 6)
- Admin UI templates content (Phase 2-4)
- python-quickbooks integration (Phase 5)

### Success Criteria

1. Running `uvicorn app.main:app` starts FastAPI server without errors
2. Running `alembic upgrade head` creates database with 4 tables
3. All models can be imported: `from app.models import QboCompany, ApiKey, AdminUser, RequestLog`
4. Settings load from `.env` file correctly with validation
5. Health endpoint returns `{"status": "healthy"}`
6. All placeholder directories exist for future phases

---

## Acceptance Criteria

### AC1: Project Directory Structure

**Given** an empty `fpqbo/fortium-qbo/` directory
**When** Phase 1 is complete
**Then** the following complete structure exists:

```
fortium-qbo/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── qbo_company.py
│   │   ├── api_key.py
│   │   ├── admin_user.py
│   │   └── request_log.py
│   ├── routers/
│   │   └── __init__.py          # Placeholder for Phase 2+
│   ├── services/
│   │   └── __init__.py          # Placeholder for Phase 3+
│   └── templates/
│       └── .gitkeep             # Placeholder for Phase 2+
├── static/
│   ├── css/
│   │   └── .gitkeep
│   └── js/
│       └── .gitkeep
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── alembic.ini
├── data/                        # gitignored - SQLite database location
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

**Test Scenario:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
find . -type d | grep -E "(models|routers|services|templates|static)" | wc -l
# Should output: 6 (models, routers, services, templates, static/css, static/js)
```

---

### AC2: SQLAlchemy Models with Relationships

**Given** the database schema from the design document
**When** models are implemented
**Then** all four models are fully typed with SQLAlchemy 2.0 style and include relationships:

#### QboCompany Model
| Field | Type | Constraints |
|-------|------|-------------|
| id | Integer | Primary key, autoincrement |
| name | String(100) | Not null |
| code | String(10) | Unique, not null, indexed |
| realm_id | String(50) | Not null |
| access_token | Text | Nullable |
| refresh_token | Text | Nullable |
| token_expires_at | DateTime | Nullable |
| token_status | String(20) | Default 'active' |
| last_refreshed_at | DateTime | Nullable |
| created_at | DateTime | Default now |

**Relationships:**
- `api_keys`: One-to-many → ApiKey (back_populates="company")

#### ApiKey Model
| Field | Type | Constraints |
|-------|------|-------------|
| id | Integer | Primary key, autoincrement |
| key_hash | String(64) | Unique, not null, indexed |
| key_prefix | String(12) | Not null |
| name | String(100) | Not null |
| company_id | Integer | Foreign key → qbo_companies.id, not null |
| is_active | Boolean | Default True |
| created_at | DateTime | Default now |
| last_used_at | DateTime | Nullable |

**Relationships:**
- `company`: Many-to-one → QboCompany (back_populates="api_keys")
- `request_logs`: One-to-many → RequestLog (back_populates="api_key")

#### AdminUser Model
| Field | Type | Constraints |
|-------|------|-------------|
| id | Integer | Primary key, autoincrement |
| email | String(255) | Unique, not null, indexed |
| is_super_admin | Boolean | Default False |
| created_at | DateTime | Default now |
| last_login_at | DateTime | Nullable |

**Relationships:** None (standalone)

#### RequestLog Model
| Field | Type | Constraints |
|-------|------|-------------|
| id | Integer | Primary key, autoincrement |
| api_key_id | Integer | Foreign key → api_keys.id, nullable |
| endpoint | String(255) | Not null |
| method | String(10) | Not null |
| status_code | Integer | Not null |
| created_at | DateTime | Default now, indexed |

**Relationships:**
- `api_key`: Many-to-one → ApiKey (back_populates="request_logs"), nullable

**Test Scenario:**
```python
from app.models import QboCompany, ApiKey, AdminUser, RequestLog
from app.database import Base

# Verify all models registered
assert len(Base.metadata.tables) == 4

# Verify relationships exist
assert hasattr(QboCompany, 'api_keys')
assert hasattr(ApiKey, 'company')
assert hasattr(ApiKey, 'request_logs')
assert hasattr(RequestLog, 'api_key')
```

**Relationship Traversal Test:**
```python
from app.database import SessionLocal
from app.models import QboCompany, ApiKey

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

# Verify relationship traversal works
db.refresh(company)
assert len(company.api_keys) == 1
assert company.api_keys[0].name == "Test Key"
assert api_key.company.code == "test"

db.rollback()
db.close()
```

---

### AC3: Alembic Migrations

**Given** SQLAlchemy models are defined
**When** Alembic is configured
**Then:**

1. `alembic.ini` exists with database URL loaded from environment
2. `alembic/env.py` imports all models for autogenerate support
3. Initial migration `001_initial_schema.py` creates all 4 tables with:
   - Correct columns and types
   - Foreign key constraints
   - Indexes on: `code`, `key_hash`, `email`, `created_at`
4. Running `alembic upgrade head` succeeds without errors

**Test Scenario:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
alembic upgrade head
sqlite3 data/fortium-qbo.db ".tables"
# Output: admin_users  api_keys  qbo_companies  request_log

sqlite3 data/fortium-qbo.db ".schema api_keys" | grep -c "FOREIGN KEY"
# Output: 1
```

---

### AC4: Pydantic Settings Configuration

**Given** environment variables from design document
**When** settings are loaded
**Then** all configuration is available via `app.config.settings`:

| Setting | Type | Default | Required |
|---------|------|---------|----------|
| app_secret_key | SecretStr | - | **Yes** (min 32 chars) |
| session_max_age_days | int | 30 | No |
| debug | bool | False | No |
| google_client_id | str | - | **Yes** |
| google_client_secret | SecretStr | - | **Yes** |
| google_allowed_domain | str | "fortiumpartners.com" | No |
| initial_admin_email | str | None | No |
| qbo_client_id | str | None | No |
| qbo_client_secret | SecretStr | None | No |
| database_url | str | "sqlite:///./data/fortium-qbo.db" | No |
| base_url | str | "http://localhost:8000" | No |

**Validation Rules:**
- `app_secret_key` must be at least 32 characters
- `google_client_id` must be non-empty
- `google_client_secret` must be non-empty

**Test Scenario:**
```python
from app.config import settings

assert settings.debug == False
assert settings.database_url.startswith("sqlite")
assert settings.google_allowed_domain == "fortiumpartners.com"
assert len(settings.app_secret_key.get_secret_value()) >= 32
```

**Error Scenario:**
```bash
# With missing GOOGLE_CLIENT_ID
unset GOOGLE_CLIENT_ID
python -c "from app.config import settings"
# Should raise ValidationError: google_client_id field required
```

---

### AC5: FastAPI Application

**Given** all infrastructure components
**When** the FastAPI app is created
**Then:**

1. App has proper metadata:
   - title: "fortium-qbo"
   - description: "QuickBooks Online API Gateway"
   - version: "0.1.0"
2. Lifespan context manager handles startup/shutdown (placeholder for future use)
3. Health endpoint exists at `GET /health`
4. Static files directory mounted at `/static`
5. Database session dependency `get_db()` is available in dependencies.py
6. Docs available at `/docs` when debug=True, hidden otherwise

**Test Scenario:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
DEBUG=true uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 2
curl http://localhost:8000/health
# Output: {"status":"healthy"}

curl -s http://localhost:8000/docs | head -1
# Should return HTML (docs page accessible)
```

---

### AC6: Requirements and Dependencies

**Given** the tech stack decisions
**When** requirements.txt is created
**Then** it includes (with minimum versions):

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

**Test Scenario:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -c "from app.main import app; print('OK')"
# Output: OK
```

---

### AC7: Git Configuration

**Given** the project structure
**When** .gitignore is created
**Then** it excludes:

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
```

**Test Scenario:**
```bash
cat .gitignore | grep -E "^data/$|^venv/$|^\.env$" | wc -l
# Output: 3
```

---

### AC8: Environment Example File

**Given** the required configuration
**When** .env.example is created
**Then** it contains all settings with placeholder values:

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

---

### AC9: README Documentation

**Given** the project structure
**When** README.md is created
**Then** it includes:

1. **Project title and description**
2. **Quick start instructions:**
   - Clone/navigate to directory
   - Create virtual environment
   - Install dependencies
   - Copy .env.example to .env and configure
   - Run migrations
   - Start server
3. **Project structure overview**
4. **Link to design document**

**Test Scenario:**
```bash
head -20 README.md | grep -c "fortium-qbo"
# Output: >= 1
```

---

## Technical Notes

### Pattern Reference: pipelinemgr

The implementation should follow patterns established in `/Users/burke/projects/pipelinemgr/`:

- **Models:** Use SQLAlchemy 2.0 `Mapped` and `mapped_column` syntax with `relationship()`
- **Database:** Use `DeclarativeBase` with proper session management via generator
- **Config:** Use `pydantic_settings.BaseSettings` with `.env` support and `@lru_cache`
- **App:** Use `@asynccontextmanager` for lifespan events

### File References

| Pattern | Reference File |
|---------|----------------|
| Model structure | `pipelinemgr/app/models/company.py` |
| Model relationships | `pipelinemgr/app/models/deal.py` |
| Database setup | `pipelinemgr/app/database.py` |
| Config pattern | `pipelinemgr/app/config.py` |
| App structure | `pipelinemgr/app/main.py` |

### Indexes

The following indexes should be created for query performance:
- `qbo_companies.code` - Lookup by company code
- `api_keys.key_hash` - API key validation
- `admin_users.email` - Login lookup
- `request_log.created_at` - Log queries by time

---

## Appendix

### Related Documents

- [Design Document](/Users/burke/projects/fpqbo/docs/plans/2025-12-17-fortium-qbo-design.md)
- [Linear Issue FOR-81](https://linear.app/fortiumpartners/issue/FOR-81/phase-1-core-infrastructure)

### Phase Dependencies

```
Phase 1 (This PRD) ──► Phase 2 (Admin Auth)
                  └──► Phase 3 (QBO Tokens)
                  └──► Phase 4 (API Keys)
                  └──► Phase 5 (QBO Gateway)
                  └──► Phase 6 (Deployment)
```

All subsequent phases depend on Phase 1 completion.

### Checklist for Phase 1 Completion

- [ ] Directory structure created with all placeholders
- [ ] All 4 SQLAlchemy models with relationships
- [ ] Alembic configured with initial migration
- [ ] Pydantic settings with validation
- [ ] FastAPI app with health endpoint
- [ ] requirements.txt with all dependencies
- [ ] .gitignore configured
- [ ] .env.example with all settings
- [ ] README.md with setup instructions
- [ ] `alembic upgrade head` succeeds
- [ ] `uvicorn app.main:app` starts without errors
- [ ] `curl /health` returns 200
