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

## Authentication Setup

### Google OAuth Configuration

1. **Create OAuth 2.0 Credentials:**
   - Visit [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   - Create new project or select existing project
   - Enable "Google+ API" (for profile info)
   - Create "OAuth 2.0 Client ID" credentials
   - Application type: "Web application"

2. **Configure Authorized Redirect URIs:**
   ```
   http://localhost:8000/auth/callback    (local development)
   https://your-domain.com/auth/callback  (production)
   ```

3. **Update .env:**
   ```bash
   cp .env.example .env
   # Edit .env and set:
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   INITIAL_ADMIN_EMAIL=your-email@fortiumpartners.com
   ```

4. **Start application:**
   ```bash
   uvicorn app.main:app --reload
   ```

   On first startup, the initial admin user will be created automatically.

5. **Access admin UI:**
   - Visit http://localhost:8000/login
   - Click "Sign in with Google"
   - Authenticate with your @fortiumpartners.com Google account

### Adding Additional Admins

Currently, admin users must be added directly to the database:

```bash
sqlite3 data/fortium-qbo.db
INSERT INTO admin_users (email, is_super_admin, created_at)
VALUES ('newadmin@fortiumpartners.com', 0, datetime('now'));
```

Admin management UI will be added in a future phase.

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

- ✅ **Phase 1:** Core Infrastructure
- ✅ **Phase 2:** Admin UI - Google OAuth authentication (this phase)
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
