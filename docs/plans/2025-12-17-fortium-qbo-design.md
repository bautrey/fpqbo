# fortium-qbo Design Document

**Date:** 2025-12-17
**Status:** Approved
**Domain:** qbotools.com

## Overview

fortium-qbo is a multi-tenant QuickBooks Online API gateway that provides a secure, unified interface for all Fortium applications to interact with QBO.

### Problem Statement

Currently, QBO integration is handled directly by Make.com modules, which:
- Don't support complex tax logic (Canadian HST)
- Require manual token management
- Lack visibility into API usage across applications

### Solution

A centralized API gateway that:
- Wraps `python-quickbooks` SDK for comprehensive entity support
- Manages OAuth tokens with auto-refresh
- Provides per-consumer API keys with audit logging
- Exposes a simple REST API for all Fortium applications

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     fortium-qbo                         │
│                    (qbotools.com)                       │
├─────────────────────────────────────────────────────────┤
│  Admin UI (FastAPI + Jinja2 + Bootstrap 5)              │
│  - Google OAuth (fortiumpartners.com + allowlist)       │
│  - API key management (create, revoke, list)            │
│  - QBO company/token status (view, re-auth)             │
│  - User management (super_admin only)                   │
├─────────────────────────────────────────────────────────┤
│  REST API (/api/v1/*)                                   │
│  - Per-consumer API key auth (X-API-Key header)         │
│  - CRUD for all QBO entities                            │
│  - API key → QBO company mapping                        │
├─────────────────────────────────────────────────────────┤
│  python-quickbooks SDK wrapper                          │
│  - Token auto-refresh                                   │
│  - Multi-company support (US, Canada)                   │
├─────────────────────────────────────────────────────────┤
│  SQLite + SQLAlchemy (Render persistent disk)           │
│  - API keys, QBO companies, admin users, request log    │
└─────────────────────────────────────────────────────────┘
```

### Consumers

- Make.com scenarios
- n8n workflows
- PartnerConnect frontend
- PartnerConnect backend
- pipelinemgr
- Future Fortium applications

## Database Schema

### qbo_companies

Stores QBO company credentials and token status.

```sql
CREATE TABLE qbo_companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- "Fortium US", "Fortium Canada"
    code TEXT UNIQUE NOT NULL,       -- "us", "ca"
    realm_id TEXT NOT NULL,          -- QBO company ID
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at DATETIME,
    token_status TEXT DEFAULT 'active',  -- active, expiring, expired, error
    last_refreshed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### api_keys

Per-consumer API keys, each scoped to one QBO company.

```sql
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    key_hash TEXT UNIQUE NOT NULL,   -- SHA256 of the actual key
    key_prefix TEXT NOT NULL,        -- First 8 chars for display ("ftm_abc1...")
    name TEXT NOT NULL,              -- "PartnerConnect-CA", "Make.com-US"
    company_id INTEGER NOT NULL REFERENCES qbo_companies(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME
);
```

### admin_users

Allowed admin UI users (subset of fortiumpartners.com).

```sql
CREATE TABLE admin_users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,      -- burke@fortiumpartners.com
    is_super_admin BOOLEAN DEFAULT FALSE,  -- can add/remove users
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME
);
```

### request_log

Lightweight audit trail for API requests.

```sql
CREATE TABLE request_log (
    id INTEGER PRIMARY KEY,
    api_key_id INTEGER REFERENCES api_keys(id),
    endpoint TEXT,
    method TEXT,
    status_code INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## REST API Design

### Authentication

All `/api/v1/*` endpoints require `X-API-Key` header. The API key determines which QBO company is targeted.

### Base URL

```
https://qbotools.com/api/v1
```

### Entity Endpoints

Standard CRUD pattern for all QBO entities:

```
# Bills
GET    /api/v1/bills              # List bills (supports ?query= for filtering)
GET    /api/v1/bills/{id}         # Get single bill
POST   /api/v1/bills              # Create bill
PUT    /api/v1/bills/{id}         # Update bill
DELETE /api/v1/bills/{id}         # Delete/void bill

# Invoices
GET    /api/v1/invoices
GET    /api/v1/invoices/{id}
POST   /api/v1/invoices
PUT    /api/v1/invoices/{id}
DELETE /api/v1/invoices/{id}

# Same pattern for:
# - customers
# - vendors
# - accounts
# - payments
# - items
# - purchase-orders
# - credit-memos
# - (all entities supported by python-quickbooks)
```

### Utility Endpoints

```
GET    /api/v1/reports/trial-balance    # Trial Balance report
GET    /api/v1/reports/profit-loss      # P&L report
GET    /api/v1/query?q=SELECT...        # Raw QBO query passthrough
GET    /health                          # Service health + token status
```

### Response Format

Success:
```json
{
  "data": { ... },
  "meta": {
    "company": "ca",
    "request_id": "req_abc123"
  }
}
```

Error:
```json
{
  "error": {
    "code": "INVALID_ENTITY",
    "message": "Bill not found",
    "details": { ... }
  }
}
```

## Admin UI

### URL

```
https://qbotools.com/admin
```

### Authentication

Two-layer authentication:
1. Google OAuth - must be `@fortiumpartners.com`
2. Allowlist - must exist in `admin_users` table

First user seeded via environment variable:
```
INITIAL_ADMIN_EMAIL=burke@fortiumpartners.com
```

### Auth Routes

```
GET  /auth/login     # Login page with Google button
GET  /auth/google    # Initiate OAuth flow
GET  /auth/callback  # Handle Google callback, create session
GET  /auth/logout    # Clear session
```

### Admin Pages

**Dashboard (`/admin`)**
- QBO company cards showing token status (green/yellow/red)
- Token expiry countdown
- Quick stats: API keys active, requests today

**Companies (`/admin/companies`)**
- List all QBO companies
- Token status indicator
- "Re-authorize" button → initiates QBO OAuth flow
- Last successful refresh timestamp

**API Keys (`/admin/keys`)**
- List all keys (prefix, name, company, last used)
- Create new key → displays once, then only shows prefix
- Revoke key (soft delete)
- Filter by company

**Users (`/admin/users`)** - super_admin only
- List allowed users
- Add new user (email + super_admin flag)
- Remove user (can't remove yourself)

**Request Log (`/admin/logs`)**
- Recent requests: timestamp, key name, endpoint, status
- Basic filtering by date, key, endpoint

### UI Stack

- FastAPI + Jinja2 templates
- Bootstrap 5 + Bootstrap Icons
- Vanilla JS for interactivity
- No build step

## Technical Decisions

### SDK Choice

**python-quickbooks** (community-maintained)
- Version 0.9.12 (April 2025) - actively maintained
- Comprehensive entity coverage
- Uses Intuit's official `intuit-oauth` package
- MIT license
- Intuit does not provide an official Python SDK

### Database

**SQLite with Render persistent disk**
- Simple, no external dependency
- Sufficient for low-volume admin tool
- Render paid plan provides persistent disk

### Token Management

- Tokens stored in database, encrypted at rest
- Background job checks token expiry
- Auto-refresh before expiration
- Status tracking: active, expiring, expired, error
- Admin UI shows token health

### QBO Company Selection

API key is bound to one QBO company at creation time. Consumers don't specify company per-request.

## Project Structure

```
fpqbo/
├── fortium-qbo/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, lifespan, routers
│   │   ├── config.py               # Pydantic settings
│   │   ├── database.py             # SQLAlchemy setup
│   │   ├── dependencies.py         # Auth deps, DB session
│   │   │
│   │   ├── models/
│   │   │   ├── api_key.py
│   │   │   ├── qbo_company.py
│   │   │   ├── admin_user.py
│   │   │   └── request_log.py
│   │   │
│   │   ├── routers/
│   │   │   ├── api.py              # /api/v1/* - QBO entity endpoints
│   │   │   ├── auth.py             # /auth/* - Google OAuth
│   │   │   └── admin.py            # /admin/* - UI pages
│   │   │
│   │   ├── services/
│   │   │   ├── qbo_client.py       # python-quickbooks wrapper
│   │   │   └── token_manager.py    # Auto-refresh, status tracking
│   │   │
│   │   └── templates/
│   │       ├── base.html
│   │       ├── login.html
│   │       └── admin/
│   │           ├── dashboard.html
│   │           ├── companies.html
│   │           ├── keys.html
│   │           ├── users.html
│   │           └── logs.html
│   │
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/app.js
│   │
│   ├── alembic/
│   ├── alembic.ini
│   ├── data/                       # SQLite DB (gitignored)
│   ├── Dockerfile
│   ├── render.yaml
│   ├── requirements.txt
│   └── README.md
```

## Environment Variables

```bash
# Application
APP_SECRET_KEY=<random-32-bytes>
SESSION_MAX_AGE_DAYS=30

# Google OAuth (Admin UI)
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxx
GOOGLE_ALLOWED_DOMAIN=fortiumpartners.com
INITIAL_ADMIN_EMAIL=burke@fortiumpartners.com

# QBO OAuth (for token acquisition)
QBO_CLIENT_ID=<intuit-app-client-id>
QBO_CLIENT_SECRET=<intuit-app-client-secret>

# Database
DATABASE_URL=sqlite:///./data/fortium-qbo.db

# Deployment
BASE_URL=https://qbotools.com
```

## Deployment

### Hosting

Render.com (existing paid account)
- Extend current `oauth-service` deployment
- Rename to `fortium-qbo`
- Custom domain: qbotools.com

### Migration Path

1. Create new directory structure in `fpqbo/fortium-qbo/`
2. Migrate existing OAuth code from `oauth-service/`
3. Add new functionality incrementally
4. Update Render deployment
5. Configure qbotools.com DNS

## Future Enhancements

- **Combination operations** - Higher-level endpoints that orchestrate multiple QBO calls (e.g., create invoice + related bills)
- **Webhooks** - Receive QBO change notifications
- **Rate limiting** - Per-consumer rate limits
- **Analytics dashboard** - Usage trends, popular endpoints
