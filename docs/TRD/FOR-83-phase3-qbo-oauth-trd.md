# TRD: Phase 3 - QBO OAuth Token Management

**Issue:** [FOR-83](https://linear.app/fortiumpartners/issue/FOR-83/phase-3-qbo-oauth-token-management)
**PRD:** [FOR-83 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-83-phase3-qbo-oauth.md)
**Project:** fortium-qbo
**Date:** 2025-12-31
**Status:** Ready for Implementation
**Version:** 2.2

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-31 | Initial TRD creation |
| 1.1 | 2025-12-31 | Refined: Fixed Jinja2 datetime handling, added admin nav |
| 2.0 | 2025-12-31 | Complete rewrite: Comprehensive architecture, detailed code snippets, checkbox tracking |
| 2.1 | 2025-12-31 | Stakeholder feedback: Use BASE_URL (no hardcoded ports), add realm_id index via Alembic migration, HTML error pages for OAuth flows, best-effort token revocation per RFC 7009, realistic time estimates (~30 min total vs 11 hours - patterns exist from Phase 1/2) |
| 2.2 | 2025-12-31 | QA review: Added Execution Environment, Git Workflow, Linear Lifecycle, Required Skills sections |

---

## Executive Summary

This TRD defines the technical implementation for Phase 3 QBO OAuth Token Management. The phase introduces self-service QBO company connection via OAuth flow, database-driven token storage, and an admin UI for managing QBO companies.

### Key Deliverables

1. **QBO OAuth Router** - New router (`qbo_oauth.py`) with connect, callback, disconnect, and refresh endpoints
2. **Admin Companies Page** - New template (`admin/companies.html`) for managing QBO company connections
3. **Config Updates** - Required QBO OAuth configuration settings with validation
4. **QBOService Enhancements** - Add `get_company_by_code()` method and error handling for disconnected companies
5. **Token Status Utility** - Reusable utility for computing token health status
6. **Database Migration** - Alembic migration to add index on `realm_id` column

### Stakeholder Decisions (v2.1)

| Decision | Resolution | Rationale |
|----------|------------|-----------|
| Port Configuration | Use `BASE_URL` from .env | Configurable, no hardcoded ports |
| Database Index | Add index on `realm_id` via Alembic | Performance for company lookup |
| OAuth Error Response | HTML error pages | Best practice for browser OAuth flows |
| Token Revocation | Yes, best-effort per RFC 7009 | Security best practice |
| Time Estimates | ~30 min total | Patterns exist from Phase 1/2, mostly copy-paste |

### Dependencies

- **Phase 1** (Complete): Database models (`QboCompany`), config, FastAPI app structure
- **Phase 2** (Complete): Admin authentication via Google OAuth, session cookies (`auth_session`), session verification

---

## Execution Environment

**Worktree:** `/Users/burke/projects/fpqbo`
**App Directory:** `/Users/burke/projects/fpqbo/fortium-qbo`
**Branch:** `feature/for-83-qbo-oauth`

---

## Git Workflow

**Branch:** `feature/for-83-qbo-oauth`
**Commits:** Conventional commits (`feat:`, `fix:`, `refactor:`)
**PR Title:** `feat(FOR-83): Phase 3 QBO OAuth token management`

---

## Linear Lifecycle

| Phase | Linear Status | Trigger |
|-------|---------------|---------|
| Start | Backlog → In Progress | Implementation begins |
| Sprint 1 Complete | Update comment | T1.1-T1.7 done |
| Sprint 2 Complete | Update comment | T2.1-T2.6 done |
| Sprint 3 Complete | In Progress → Review | All tasks done, PR created |
| Merged | Review → Done | PR merged |

---

## Required Skills

- `backend-developer` - FastAPI router, database operations
- `frontend-developer` - Bootstrap template (admin/companies.html)

### UI Testing

Use **Chrome DevTools MCP** to verify:
- [ ] `/admin/companies` page renders correctly
- [ ] Connect button triggers OAuth flow
- [ ] Status badges display correct colors
- [ ] Disconnect confirmation dialog works
- [ ] Flash messages appear after actions

---

## System Architecture

### Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                   Admin Browser                                    |
+-----------------------------------------------------------------------------------+
              |                            |                           |
              v                            v                           v
    +------------------+        +------------------+         +------------------+
    | /admin/companies |        | /api/qbo/connect |         | /api/qbo/callback|
    | (GET - HTML)     |        | (GET - Redirect) |         | (GET - Handler)  |
    +------------------+        +------------------+         +------------------+
              |                            |                           |
              v                            v                           v
    +-----------------------------------------------------------------------------------+
    |                            pages.py / qbo_oauth.py (Routers)                      |
    +-----------------------------------------------------------------------------------+
              |                            |                           |
              |                            v                           v
              |                 +----------------------+    +----------------------+
              |                 | Intuit OAuth Server  |    | Token Exchange       |
              |                 | (Authorization)      |    | (intuitlib.AuthClient)
              |                 +----------------------+    +----------------------+
              |                                                        |
              v                                                        v
    +-----------------------------------------------------------------------------------+
    |                             QBOService (services/qbo_service.py)                  |
    |  - _get_company()        - _needs_refresh()     - _refresh_token()                |
    |  - get_company_by_code() (NEW)                  - _get_company_by_realm() (EXISTS)|
    +-----------------------------------------------------------------------------------+
              |
              v
    +-----------------------------------------------------------------------------------+
    |                             SQLite Database (data/fortium-qbo.db)                 |
    |                                                                                   |
    |   qbo_companies: id, name, code, realm_id (INDEXED), access_token, refresh_token, |
    |                  token_expires_at, token_status, last_refreshed_at, created_at    |
    +-----------------------------------------------------------------------------------+
```

### OAuth Flow Sequence Diagram

```
     Admin                Browser                  fortium-qbo                 Intuit OAuth
       |                    |                          |                           |
       |  1. Click "Connect"|                          |                           |
       |------------------->|                          |                           |
       |                    |  2. GET /admin/companies |                           |
       |                    |------------------------->|                           |
       |                    |  3. HTML with button     |                           |
       |                    |<-------------------------|                           |
       |  4. Click button   |                          |                           |
       |------------------->|                          |                           |
       |                    |  5. GET /api/qbo/connect |                           |
       |                    |------------------------->|                           |
       |                    |                          | 6. Generate state         |
       |                    |                          | 7. Store state in session |
       |                    |  8. 302 Redirect         |                           |
       |                    |<-------------------------|                           |
       |                    |  9. GET /connect/oauth2?client_id=...&state=...     |
       |                    |-------------------------------------------------------->|
       |                    |  10. Consent screen      |                           |
       |                    |<---------------------------------------------------------|
       | 11. Approve        |                          |                           |
       |------------------->|                          |                           |
       |                    |  12. 302 callback?code=...&state=...&realmId=...    |
       |                    |<---------------------------------------------------------|
       |                    |  13. GET /api/qbo/callback?code=...&state=...        |
       |                    |------------------------->|                           |
       |                    |                          | 14. Validate state        |
       |                    |                          | 15. Exchange code         |
       |                    |                          |-------------------------->|
       |                    |                          | 16. Tokens returned       |
       |                    |                          |<--------------------------|
       |                    |                          | 17. Fetch company info    |
       |                    |                          |-------------------------->|
       |                    |                          | 18. Company name          |
       |                    |                          |<--------------------------|
       |                    |                          | 19. Save to database      |
       |                    |  20. 302 /admin/companies?message=connected          |
       |                    |<-------------------------|                           |
       |                    |  21. GET /admin/companies                            |
       |                    |------------------------->|                           |
       |                    |  22. HTML with company   |                           |
       |                    |<-------------------------|                           |
       | 23. See success    |                          |                           |
       |<-------------------|                          |                           |
```

### Token Refresh Flow

```
QBOService.get_invoices(company_id)
         |
         v
_get_client(company)
         |
         +-- _needs_refresh(company)?
         |        |
         |        +-- token_expires_at <= now + 5 min? -> Yes
         |                                              |
         |                                              v
         |                                    _refresh_token(company)
         |                                              |
         |                                              +-- Call Intuit token endpoint
         |                                              +-- Update company record
         |                                              +-- Commit to database
         |
         v
Create QuickBooks client with fresh token
         |
         v
Make API request
```

### Existing Infrastructure (No Changes Required)

| Component | Location | Status |
|-----------|----------|--------|
| QBOService | `app/services/qbo_service.py` | Token refresh working |
| QboCompany model | `app/models/qbo_company.py` | All fields present |
| SessionMiddleware | `app/main.py` | Added in Phase 2 |
| Session service | `app/services/session_service.py` | verify_session() working |
| Admin auth patterns | `app/routers/pages.py` | Cookie-based auth working |

---

## Master Task List

### Task Summary by Sprint

| Sprint | Description | Tasks | Est. Time | Priority |
|--------|-------------|-------|-----------|----------|
| Sprint 1 | Configuration & Core OAuth | T1.1 - T1.7 | 15 min | P0 |
| Sprint 2 | Admin UI & Token Management | T2.1 - T2.6 | 10 min | P0 |
| Sprint 3 | Testing & Documentation | T3.1 - T3.6 | 5 min | P0 |
| **Total** | | **19 tasks** | **~30 min** | |

**Note:** Time estimates reflect that all patterns exist from Phase 1/2. Implementation is primarily copy-paste with minor modifications.

---

## Sprint 1: Configuration & Core OAuth Router (15 min)

### T1.1: Update config.py with QBO OAuth Settings

**File:** `app/config.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Changes:**
- Add `qbo_redirect_uri` optional field with default logic
- Add computed property for effective redirect URI
- Keep existing optional qbo_client_id/qbo_client_secret for backward compatibility

**Code:**

```python
# QBO OAuth (Optional - for Phase 3+)
qbo_client_id: str | None = None
qbo_client_secret: SecretStr | None = None
qbo_redirect_uri: str | None = None  # Defaults to {base_url}/api/qbo/callback

# DEPRECATED - tokens now stored in database (kept for migration)
qbo_access_token: SecretStr | None = None
qbo_refresh_token: str | None = None
qbo_company_id: str | None = None

@property
def qbo_callback_url(self) -> str:
    """Get QBO OAuth callback URL."""
    return self.qbo_redirect_uri or f"{self.base_url}/api/qbo/callback"

@property
def qbo_configured(self) -> bool:
    """Check if QBO OAuth is configured."""
    return bool(self.qbo_client_id and self.qbo_client_secret)
```

**Acceptance Criteria:**
- [ ] AC1: qbo_callback_url property returns correct URL using BASE_URL
- [ ] AC1: qbo_configured property returns True when both credentials set

---

### T1.2: Create qbo_oauth.py Router Skeleton

**File:** `app/routers/qbo_oauth.py` (NEW)
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
"""QBO OAuth router for QuickBooks Online connection management."""

import logging
import secrets
import string
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from sqlalchemy import select
from sqlalchemy.orm import Session
import httpx

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import AdminUser
from app.models.qbo_company import QboCompany
from app.services.session_service import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qbo", tags=["qbo-oauth"])


def _require_auth(request: Request) -> str:
    """
    Verify admin authentication from session cookie.

    Returns email if authenticated.
    Raises RedirectResponse to /login if not authenticated.
    """
    session_token = request.cookies.get("auth_session")
    if not session_token:
        raise RedirectResponse(url="/login", status_code=302)

    email = verify_session(session_token)
    if not email:
        raise RedirectResponse(url="/login", status_code=302)

    # Verify user exists in admin_users
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            raise RedirectResponse(url="/login", status_code=302)

        return email
    finally:
        db.close()


def _get_intuit_auth_client(
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> AuthClient:
    """Create Intuit AuthClient with configured credentials."""
    return AuthClient(
        client_id=settings.qbo_client_id,
        client_secret=settings.qbo_client_secret.get_secret_value(),
        access_token=access_token,
        refresh_token=refresh_token,
        environment="production",
        redirect_uri=settings.qbo_callback_url,
    )


def _error_response(message: str, status_code: int = 400) -> HTMLResponse:
    """
    Generate HTML error page for OAuth failures.

    Per stakeholder decision: HTML error pages are best practice for browser OAuth flows.
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>QuickBooks Connection Error - fortium-qbo</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="row justify-content-center">
                <div class="col-md-6">
                    <div class="card border-danger">
                        <div class="card-header bg-danger text-white">
                            <h5 class="mb-0">QuickBooks Connection Error</h5>
                        </div>
                        <div class="card-body">
                            <p class="card-text">{message}</p>
                            <a href="/admin/companies" class="btn btn-primary">Back to Companies</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=status_code)
```

**Acceptance Criteria:**
- [ ] AC11: _require_auth() redirects unauthenticated users to /login
- [ ] Router structure follows existing patterns (auth.py, pages.py)

---

### T1.3: Implement GET /api/qbo/connect

**File:** `app/routers/qbo_oauth.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
@router.get("/connect")
async def qbo_connect(request: Request):
    """
    Initiate QBO OAuth flow.

    1. Verify admin authentication
    2. Generate state parameter for CSRF protection
    3. Store state in session
    4. Redirect to Intuit OAuth consent screen

    Returns:
        302 Redirect to Intuit OAuth authorization URL
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"QBO OAuth connect initiated by {email}")
    except RedirectResponse as redirect:
        return redirect

    # Check QBO credentials configured
    if not settings.qbo_configured:
        logger.error("QBO OAuth not configured")
        return _error_response(
            "QBO OAuth not configured. Set QBO_CLIENT_ID and QBO_CLIENT_SECRET environment variables."
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state in session (uses SessionMiddleware)
    request.session["qbo_oauth_state"] = state

    # Build authorization URL
    auth_client = _get_intuit_auth_client()

    auth_url = auth_client.get_authorization_url(
        scopes=[Scopes.ACCOUNTING],
        state_token=state,
    )

    logger.info(f"Redirecting to Intuit OAuth, state={state[:8]}...")

    return RedirectResponse(url=auth_url, status_code=302)
```

**Acceptance Criteria:**
- [ ] AC2: Redirect URL contains correct client_id
- [ ] AC2: Redirect URL requests com.intuit.quickbooks.accounting scope
- [ ] AC2: Redirect URL includes state parameter for CSRF
- [ ] AC2: State is stored in session for callback validation
- [ ] AC11: Requires authenticated admin session

---

### T1.4: Implement GET /api/qbo/callback

**File:** `app/routers/qbo_oauth.py`
**Estimated Time:** 3 minutes
**Status:** [ ] Not Started

**Code:**

```python
@router.get("/callback")
async def qbo_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    realmId: str | None = None,
    error: str | None = None,
):
    """
    Handle OAuth callback from Intuit.

    1. Validate state parameter matches session (CSRF protection)
    2. Exchange authorization code for access and refresh tokens
    3. Fetch company info from QBO API
    4. Create or update qbo_companies record
    5. Redirect to admin companies page with success message

    Returns:
        302 Redirect to /admin/companies on success
        HTML error page on failure (per stakeholder decision)
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"QBO OAuth callback received for {email}")
    except RedirectResponse as redirect:
        return redirect

    # Handle OAuth error from Intuit
    if error:
        logger.error(f"QBO OAuth error from Intuit: {error}")
        return _error_response(f"QuickBooks authorization was denied: {error}")

    # Validate required parameters
    if not code:
        logger.error("Missing authorization code in callback")
        return _error_response("Authorization code missing. Please try again.")

    if not realmId:
        logger.error("Missing realmId in callback")
        return _error_response("Company ID missing. Please try again.")

    # Validate state (CSRF protection)
    stored_state = request.session.get("qbo_oauth_state")
    if not stored_state or stored_state != state:
        logger.error(f"State mismatch: stored={stored_state[:8] if stored_state else None}..., received={state[:8] if state else None}...")
        return _error_response("Invalid state parameter. Please try again.")

    # Clear state from session
    del request.session["qbo_oauth_state"]

    try:
        # Exchange code for tokens
        auth_client = _get_intuit_auth_client()
        auth_client.get_bearer_token(code, realm_id=realmId)

        access_token = auth_client.access_token
        refresh_token = auth_client.refresh_token

        if not access_token or not refresh_token:
            logger.error("Token exchange returned empty tokens")
            return _error_response("Unable to exchange authorization code. Please try again.")

        logger.info(f"Successfully exchanged code for tokens, realm={realmId}")

        # Fetch company info
        company_name = await _fetch_company_name(realmId, access_token)
        logger.info(f"Fetched company name: {company_name}")

        # Save to database
        db = SessionLocal()
        try:
            # Check for existing company
            existing = db.query(QboCompany).filter(
                QboCompany.realm_id == realmId
            ).first()

            if existing:
                # Update existing company
                existing.access_token = access_token
                existing.refresh_token = refresh_token
                existing.token_expires_at = datetime.utcnow() + timedelta(hours=1)
                existing.token_status = "active"
                existing.last_refreshed_at = datetime.utcnow()
                if company_name != "Unknown Company":
                    existing.name = company_name
                db.commit()
                logger.info(f"Updated existing QBO company: {existing.code}")
            else:
                # Create new company
                company_code = _generate_company_code(db, company_name)
                new_company = QboCompany(
                    name=company_name,
                    code=company_code,
                    realm_id=realmId,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expires_at=datetime.utcnow() + timedelta(hours=1),
                    token_status="active",
                    last_refreshed_at=datetime.utcnow(),
                )
                db.add(new_company)
                db.commit()
                logger.info(f"Created new QBO company: {company_code}")

        except Exception as e:
            logger.error(f"Database error saving company: {e}", exc_info=True)
            db.rollback()
            return _error_response("Failed to save company. Please try again.")
        finally:
            db.close()

        # Redirect to companies page with success
        return RedirectResponse(
            url="/admin/companies?message=connected",
            status_code=302,
        )

    except Exception as e:
        logger.error(f"Token exchange error: {e}", exc_info=True)
        return _error_response("Unable to exchange authorization code. Please try again.")


async def _fetch_company_name(realm_id: str, access_token: str) -> str:
    """Fetch company name from QBO Company Info API."""
    url = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}/companyinfo/{realm_id}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                params={"minorversion": "69"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("CompanyInfo", {}).get("CompanyName", "Unknown Company")
    except Exception as e:
        logger.warning(f"Failed to fetch company info: {e}")
        return "Unknown Company"
```

**Acceptance Criteria:**
- [ ] AC3: State parameter validated against session
- [ ] AC3: Authorization code exchanged for access/refresh tokens
- [ ] AC3: QBO Company Info API called to get company name
- [ ] AC3: New qbo_companies record created with all fields
- [ ] AC3: Admin redirected to /admin/companies with success message
- [ ] AC4: Invalid state parameter returns HTML error page
- [ ] AC4: Missing authorization code returns HTML error page
- [ ] AC4: Token exchange failure returns HTML error page
- [ ] AC4: QBO API error creates company with "Unknown Company" name
- [ ] AC4: Duplicate realm_id updates existing company

---

### T1.5: Implement Company Code Generation

**File:** `app/routers/qbo_oauth.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
import random
import re


def _generate_company_code(db: Session, company_name: str) -> str:
    """
    Generate unique company code.

    Format: First 3 chars of company name (uppercase) + "-" + 3 random digits
    Examples: "FOR-482", "TES-127", "ABC-951"

    Ensures uniqueness by checking for collisions.
    """
    # Extract first 3 alphanumeric characters
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', company_name)
    prefix = clean_name[:3].upper() if len(clean_name) >= 3 else clean_name.upper().ljust(3, 'X')

    # Try to generate unique code (max 10 attempts)
    for _ in range(10):
        suffix = f"{random.randint(0, 999):03d}"
        code = f"{prefix}-{suffix}"

        # Check for collision
        existing = db.query(QboCompany).filter(QboCompany.code == code).first()
        if not existing:
            return code

    # Fallback: use timestamp-based suffix
    import time
    suffix = str(int(time.time()))[-3:]
    return f"{prefix}-{suffix}"
```

**Acceptance Criteria:**
- [ ] FR10: Code format is 3 uppercase chars + "-" + 3 digits
- [ ] FR10: Code is unique (collision check)
- [ ] FR10: Handles short company names gracefully

---

### T1.6: Register qbo_oauth Router in main.py

**File:** `app/main.py`
**File:** `app/routers/__init__.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Changes in main.py:**

```python
# Update imports (add qbo_oauth)
from app.routers import accounts, auth, bills, customers, invoices, pages, payments, qbo_oauth, reports, vendors

# Add after existing router registrations (around line 94)
app.include_router(qbo_oauth.router)
```

**Changes in __init__.py:**

```python
from app.routers import qbo_oauth
```

**Acceptance Criteria:**
- [ ] AC10: All QBO OAuth routes accessible at /api/qbo/*
- [ ] AC10: Routes appear in OpenAPI schema (when debug=True)

---

### T1.7: Create Alembic Migration for realm_id Index

**File:** `alembic/versions/xxx_add_realm_id_index.py` (NEW)
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Migration Code:**

```python
"""Add index on qbo_companies.realm_id

Revision ID: xxx
Revises: [previous_revision]
Create Date: 2025-12-31

Per stakeholder feedback: Index on realm_id for performance on company lookup.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'xxx'  # Generate with: alembic revision -m "add_realm_id_index"
down_revision = '[previous_revision]'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_qbo_companies_realm_id', 'qbo_companies', ['realm_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_qbo_companies_realm_id', table_name='qbo_companies')
```

**Acceptance Criteria:**
- [ ] Migration creates index on realm_id column
- [ ] Index is unique (one company per realm)
- [ ] Migration is reversible

---

## Sprint 2: Admin UI & Token Management (10 min)

### T2.1: Create Token Status Utility

**File:** `app/utils/__init__.py` (create if needed)
**File:** `app/utils/token_status.py` (NEW)
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
"""Token status utility functions."""

from datetime import datetime, timedelta
from typing import NamedTuple


class TokenStatus(NamedTuple):
    """Token status with display information."""
    status: str       # "active", "expiring_soon", "expired", "disconnected"
    label: str        # Human-readable label
    css_class: str    # Bootstrap badge class
    expires_display: str  # Human-readable expiration


def get_token_status(
    token_expires_at: datetime | None,
    token_status_db: str | None = None,
) -> TokenStatus:
    """
    Calculate token status for display.

    Args:
        token_expires_at: Token expiration timestamp
        token_status_db: Status from database ("active", "disconnected", etc.)

    Returns:
        TokenStatus with status, label, CSS class, and expiration display
    """
    # Check for disconnected
    if token_status_db == "disconnected" or token_expires_at is None:
        return TokenStatus(
            status="disconnected",
            label="Disconnected",
            css_class="bg-secondary",
            expires_display="Not connected",
        )

    now = datetime.utcnow()

    # Check if expired
    if token_expires_at <= now:
        delta = now - token_expires_at
        expires_display = _format_time_ago(delta)
        return TokenStatus(
            status="expired",
            label="Expired",
            css_class="bg-danger",
            expires_display=f"Expired {expires_display}",
        )

    # Calculate time until expiration
    delta = token_expires_at - now

    # Check if expiring soon (within 30 minutes)
    if delta <= timedelta(minutes=30):
        expires_display = _format_time_remaining(delta)
        return TokenStatus(
            status="expiring_soon",
            label="Expiring Soon",
            css_class="bg-warning text-dark",
            expires_display=f"Expires in {expires_display}",
        )

    # Active
    expires_display = _format_time_remaining(delta)
    return TokenStatus(
        status="active",
        label="Active",
        css_class="bg-success",
        expires_display=f"Expires in {expires_display}",
    )


def _format_time_remaining(delta: timedelta) -> str:
    """Format time remaining as human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds} seconds"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours} hour{'s' if hours != 1 else ''}"


def _format_time_ago(delta: timedelta) -> str:
    """Format time ago as human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "just now"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = total_seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
```

**Acceptance Criteria:**
- [ ] AC6: Token status logic matches specification (Active/Expiring Soon/Expired/Disconnected)
- [ ] AC6: Human-readable time display works correctly

---

### T2.2: Create admin/companies.html Template

**File:** `app/templates/admin/companies.html` (NEW)
**Directory:** `app/templates/admin/` (create if needed)
**Estimated Time:** 3 minutes
**Status:** [ ] Not Started

**Code:**

```html
{% extends "base.html" %}

{% block title %}QBO Companies - fortium-qbo{% endblock %}

{% block content %}
<!-- Navigation Bar -->
<nav class="navbar navbar-expand-lg navbar-light bg-light mb-4">
    <div class="container">
        <a class="navbar-brand" href="/">fortium-qbo</a>
        <div class="navbar-nav">
            <a class="nav-link" href="/">Home</a>
            <a class="nav-link active" href="/admin/companies">QBO Companies</a>
        </div>
        <div class="navbar-nav ms-auto">
            <span class="nav-link text-muted">{{ user.email }}</span>
            <a class="nav-link" href="/auth/logout">Logout</a>
        </div>
    </div>
</nav>

<div class="container">
    <!-- Header -->
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="bi bi-building me-2"></i>QBO Companies</h2>
        {% if qbo_configured %}
        <a href="/api/qbo/connect" class="btn btn-success">
            <i class="bi bi-plus-circle me-2"></i>Connect QuickBooks
        </a>
        {% else %}
        <button class="btn btn-secondary" disabled title="QBO OAuth not configured">
            <i class="bi bi-plus-circle me-2"></i>Connect QuickBooks
        </button>
        {% endif %}
    </div>

    <!-- Flash Messages -->
    {% if message == "connected" %}
    <div class="alert alert-success alert-dismissible fade show" role="alert">
        <i class="bi bi-check-circle me-2"></i>Successfully connected QuickBooks company.
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% elif message == "disconnected" %}
    <div class="alert alert-info alert-dismissible fade show" role="alert">
        <i class="bi bi-info-circle me-2"></i>QuickBooks company disconnected.
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% elif message == "refreshed" %}
    <div class="alert alert-success alert-dismissible fade show" role="alert">
        <i class="bi bi-arrow-clockwise me-2"></i>Token refreshed successfully.
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% elif message == "refresh_failed" %}
    <div class="alert alert-danger alert-dismissible fade show" role="alert">
        <i class="bi bi-exclamation-triangle me-2"></i>Token refresh failed. Please reconnect.
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% endif %}

    <!-- QBO Not Configured Warning -->
    {% if not qbo_configured %}
    <div class="alert alert-warning">
        <strong><i class="bi bi-exclamation-triangle me-2"></i>QBO OAuth Not Configured</strong><br>
        Set <code>QBO_CLIENT_ID</code> and <code>QBO_CLIENT_SECRET</code> environment variables to enable QuickBooks connections.
    </div>
    {% endif %}

    <!-- Companies Table -->
    <div class="card shadow-sm">
        <div class="card-body">
            {% if companies %}
            <div class="table-responsive">
                <table class="table table-hover align-middle">
                    <thead class="table-light">
                        <tr>
                            <th>Name</th>
                            <th>Code</th>
                            <th>Realm ID</th>
                            <th>Status</th>
                            <th>Token Expiration</th>
                            <th>Last Refreshed</th>
                            <th class="text-end">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for company in companies %}
                        <tr>
                            <td class="fw-semibold">{{ company.name }}</td>
                            <td><code>{{ company.code }}</code></td>
                            <td><code class="text-muted small">{{ company.realm_id }}</code></td>
                            <td>
                                <span class="badge {{ company.token_status_info.css_class }}">
                                    {{ company.token_status_info.label }}
                                </span>
                            </td>
                            <td>{{ company.token_status_info.expires_display }}</td>
                            <td>
                                {% if company.last_refreshed_at %}
                                <small>{{ company.last_refreshed_at.strftime('%Y-%m-%d %H:%M') }} UTC</small>
                                {% else %}
                                <span class="text-muted">Never</span>
                                {% endif %}
                            </td>
                            <td class="text-end">
                                {% if company.token_status != "disconnected" %}
                                <button class="btn btn-sm btn-outline-primary me-1"
                                        onclick="refreshToken({{ company.id }})"
                                        title="Refresh Token">
                                    <i class="bi bi-arrow-clockwise"></i>
                                </button>
                                {% endif %}
                                <form action="/api/qbo/companies/{{ company.id }}/disconnect"
                                      method="POST"
                                      class="d-inline"
                                      onsubmit="return confirm('Disconnect {{ company.name }}? This will revoke API access.')">
                                    <button type="submit" class="btn btn-sm btn-outline-danger" title="Disconnect">
                                        <i class="bi bi-x-circle"></i>
                                    </button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="text-center py-5">
                <i class="bi bi-inbox display-1 text-muted"></i>
                <h4 class="mt-3 text-muted">No QBO companies connected</h4>
                <p class="text-muted">
                    {% if qbo_configured %}
                    Click "Connect QuickBooks" to add your first company.
                    {% else %}
                    Configure QBO credentials first, then connect a company.
                    {% endif %}
                </p>
            </div>
            {% endif %}
        </div>
    </div>

    <!-- Back Navigation -->
    <div class="mt-4">
        <a href="/" class="btn btn-outline-secondary">
            <i class="bi bi-arrow-left me-2"></i>Back to Home
        </a>
    </div>
</div>

{% endblock %}

{% block extra_js %}
<script>
async function refreshToken(companyId) {
    try {
        const response = await fetch(`/api/qbo/companies/${companyId}/refresh`, {
            method: 'POST',
        });
        const result = await response.json();

        if (result.success) {
            window.location.href = '/admin/companies?message=refreshed';
        } else {
            alert(result.message);
            if (result.reconnect_required) {
                window.location.href = '/admin/companies?message=refresh_failed';
            }
        }
    } catch (error) {
        alert('Failed to refresh token: ' + error.message);
    }
}
</script>
{% endblock %}
```

**Acceptance Criteria:**
- [ ] AC5: "Connect QuickBooks" button visible (disabled if not configured)
- [ ] AC5: Companies table with all specified columns
- [ ] AC5: Status badges with correct Bootstrap colors
- [ ] AC5: "Disconnect" and "Refresh" action buttons per company
- [ ] AC6: Token status displays correctly based on expiration

---

### T2.3: Add /admin/companies Route to pages.py

**File:** `app/routers/pages.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Changes:**

```python
# Add imports at top
from app.models.qbo_company import QboCompany
from app.utils.token_status import get_token_status
from app.config import settings


@router.get("/admin/companies")
async def companies_page(request: Request, message: str | None = None):
    """
    Render QBO companies management page.

    Requires authenticated admin session.
    Shows list of connected QBO companies with status.

    Query params:
        message: Flash message type ("connected", "disconnected", "refreshed", "refresh_failed")

    Returns:
        HTML companies page if authenticated
        Redirect to /login if not authenticated
    """
    # Check for session cookie
    session_token = request.cookies.get("auth_session")

    if not session_token:
        logger.info("No session cookie, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Verify session
    email = verify_session(session_token)

    if not email:
        logger.info("Invalid session token, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Get user and companies from database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            logger.warning(f"Session valid but user not in database: {email}")
            return RedirectResponse(url="/login", status_code=302)

        # Fetch all QBO companies
        companies = db.query(QboCompany).order_by(QboCompany.name).all()

        # Add token status info to each company for template
        for company in companies:
            company.token_status_info = get_token_status(
                company.token_expires_at,
                company.token_status,
            )

        # Render companies page
        return templates.TemplateResponse(
            "admin/companies.html",
            {
                "request": request,
                "user": admin_user,
                "companies": companies,
                "message": message,
                "qbo_configured": settings.qbo_configured,
            }
        )

    finally:
        db.close()
```

**Acceptance Criteria:**
- [ ] AC5: Admin companies page accessible at /admin/companies
- [ ] AC11: Requires authenticated admin session (redirects to /login if not)

---

### T2.4: Implement POST /api/qbo/companies/{id}/disconnect

**File:** `app/routers/qbo_oauth.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
@router.post("/companies/{company_id}/disconnect")
async def disconnect_company(request: Request, company_id: int):
    """
    Disconnect a QBO company by clearing tokens.

    1. Verify admin authentication
    2. Best-effort token revocation with Intuit (per RFC 7009)
    3. Clear tokens from database
    4. Redirect to companies page with success message

    Returns:
        302 Redirect to /admin/companies?message=disconnected
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"Disconnect company {company_id} requested by {email}")
    except RedirectResponse as redirect:
        return redirect

    db = SessionLocal()
    try:
        company = db.query(QboCompany).filter(QboCompany.id == company_id).first()

        if not company:
            logger.warning(f"Company not found for disconnect: {company_id}")
            return RedirectResponse(
                url="/admin/companies?message=error",
                status_code=302,
            )

        company_code = company.code

        # Best-effort token revocation with Intuit (per OAuth 2.0 RFC 7009)
        if company.refresh_token or company.access_token:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    token_to_revoke = company.refresh_token or company.access_token
                    await client.post(
                        "https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
                        data={"token": token_to_revoke},
                        auth=(
                            settings.qbo_client_id,
                            settings.qbo_client_secret.get_secret_value(),
                        ),
                    )
                logger.info(f"Revoked token with Intuit for company {company_code}")
            except Exception as e:
                logger.warning(f"Failed to revoke token with Intuit (best effort): {e}")

        # Clear tokens in database
        company.access_token = None
        company.refresh_token = None
        company.token_expires_at = None
        company.token_status = "disconnected"

        db.commit()
        logger.info(f"Disconnected QBO company: {company_code}")

        return RedirectResponse(
            url="/admin/companies?message=disconnected",
            status_code=302,
        )

    except Exception as e:
        logger.error(f"Error disconnecting company: {e}", exc_info=True)
        db.rollback()
        return RedirectResponse(
            url="/admin/companies?message=error",
            status_code=302,
        )
    finally:
        db.close()
```

**Acceptance Criteria:**
- [ ] AC7: Best-effort token revocation attempted per RFC 7009
- [ ] AC7: access_token set to NULL
- [ ] AC7: refresh_token set to NULL
- [ ] AC7: token_expires_at set to NULL
- [ ] AC7: token_status set to "disconnected"
- [ ] AC7: Admin redirected with success message
- [ ] AC7: Company still appears in list but with "Disconnected" status
- [ ] AC11: Requires authenticated admin session

---

### T2.5: Implement POST /api/qbo/companies/{id}/refresh

**File:** `app/routers/qbo_oauth.py`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Code:**

```python
@router.post("/companies/{company_id}/refresh")
async def refresh_company_token(request: Request, company_id: int):
    """
    Manually refresh a QBO company's token.

    1. Verify admin authentication
    2. Call Intuit token refresh
    3. Update token status and timestamps in database
    4. Return JSON response for AJAX handling

    Returns:
        JSON with success status and message
    """
    # Verify authentication
    try:
        email = _require_auth(request)
        logger.info(f"Manual token refresh for company {company_id} requested by {email}")
    except RedirectResponse:
        return {"success": False, "message": "Authentication required", "reconnect_required": False}

    db = SessionLocal()
    try:
        company = db.query(QboCompany).filter(QboCompany.id == company_id).first()

        if not company:
            logger.warning(f"Company not found for refresh: {company_id}")
            return {"success": False, "message": "Company not found", "reconnect_required": False}

        if company.token_status == "disconnected" or not company.refresh_token:
            logger.warning(f"Cannot refresh disconnected company: {company.code}")
            return {
                "success": False,
                "message": "No refresh token available. Please reconnect QuickBooks.",
                "reconnect_required": True,
            }

        try:
            # Refresh token using Intuit AuthClient
            auth_client = _get_intuit_auth_client(
                access_token=company.access_token,
                refresh_token=company.refresh_token,
            )
            auth_client.refresh()

            # Update company record
            company.access_token = auth_client.access_token
            company.refresh_token = auth_client.refresh_token
            company.token_expires_at = datetime.utcnow() + timedelta(hours=1)
            company.token_status = "active"
            company.last_refreshed_at = datetime.utcnow()

            db.commit()
            logger.info(f"Manually refreshed token for company {company.code}")

            return {
                "success": True,
                "message": "Token refreshed successfully",
                "expires_at": company.token_expires_at.isoformat(),
            }

        except Exception as e:
            logger.error(f"Token refresh failed for {company.code}: {e}", exc_info=True)

            # Mark as expired if refresh fails
            company.token_status = "expired"
            db.commit()

            return {
                "success": False,
                "message": "Refresh token expired. Please reconnect QuickBooks.",
                "reconnect_required": True,
            }

    except Exception as e:
        logger.error(f"Error refreshing company token: {e}", exc_info=True)
        db.rollback()
        return {"success": False, "message": f"Error: {str(e)}", "reconnect_required": False}
    finally:
        db.close()
```

**Acceptance Criteria:**
- [ ] AC8: New access token obtained from Intuit
- [ ] AC8: token_expires_at updated to 1 hour from now
- [ ] AC8: last_refreshed_at updated to current time
- [ ] AC8: token_status remains "active" on success
- [ ] AC8: Success/failure message returned as JSON
- [ ] AC11: Requires authenticated admin session

---

### T2.6: Add get_company_by_code() to QBOService

**File:** `app/services/qbo_service.py`
**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Code to add after _get_company_by_realm method:**

```python
def get_company_by_code(self, code: str) -> QboCompany:
    """
    Get QBO company by code.

    Args:
        code: Company code (e.g., "FOR-482")

    Returns:
        QboCompany instance

    Raises:
        ValueError: If company not found or disconnected
    """
    company = self.db.query(QboCompany).filter(QboCompany.code == code).first()
    if not company:
        raise ValueError(f"QBO company not found: {code}")
    if company.token_status == "disconnected":
        raise ValueError(
            f"QBO company {code} is disconnected. Please reconnect via /admin/companies."
        )
    return company
```

**Acceptance Criteria:**
- [ ] FR9: Method to look up company by code
- [ ] FR9: Clear error when company not found
- [ ] FR9: Clear error when company is disconnected

---

## Sprint 3: Testing & Documentation (5 min)

### T3.1: Update .env.example

**File:** `fortium-qbo/.env.example`
**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Content to add/update:**

```bash
# ============================================================================
# QBO OAuth (Required for Phase 3+)
# ============================================================================
# Setup Instructions:
# 1. Create app at https://developer.intuit.com/app/developer/qbo/docs/get-started
# 2. Configure redirect URI: {BASE_URL}/api/qbo/callback
#    Example: If BASE_URL=http://localhost:8086, redirect URI is http://localhost:8086/api/qbo/callback
# 3. Select scope: Accounting (com.intuit.quickbooks.accounting)
# 4. Copy Client ID and Client Secret below

QBO_CLIENT_ID=your-qbo-client-id
QBO_CLIENT_SECRET=your-qbo-client-secret

# Optional: Override redirect URI (defaults to {BASE_URL}/api/qbo/callback)
# QBO_REDIRECT_URI=https://custom-domain.com/api/qbo/callback

# DEPRECATED - Tokens now stored in database (remove after migration):
# QBO_ACCESS_TOKEN=xxx
# QBO_REFRESH_TOKEN=xxx
# QBO_COMPANY_ID=xxx
```

**Acceptance Criteria:**
- [ ] AC12: .env.example updated with QBO OAuth instructions
- [ ] AC12: Clear setup steps showing BASE_URL usage
- [ ] AC12: No hardcoded port numbers in examples

---

### T3.2: Update README.md

**File:** `fortium-qbo/README.md`
**Estimated Time:** 2 minutes
**Status:** [ ] Not Started

**Content to add:**

```markdown
## QuickBooks Connection Setup

### Intuit Developer Portal Setup

1. **Create Intuit Developer Account:**
   - Visit [Intuit Developer Portal](https://developer.intuit.com/)
   - Create account or sign in

2. **Create OAuth App:**
   - Go to Dashboard > Create an app
   - Select "QuickBooks Online and Payments"
   - App name: "fortium-qbo"

3. **Configure OAuth Settings:**
   - Redirect URIs: `{BASE_URL}/api/qbo/callback`
     - Example: If `BASE_URL=http://localhost:8086`, use `http://localhost:8086/api/qbo/callback`
   - Scopes: Select "Accounting"

4. **Get Credentials:**
   - Copy Client ID and Client Secret
   - Add to .env file:
     ```
     QBO_CLIENT_ID=your-client-id
     QBO_CLIENT_SECRET=your-client-secret
     ```

### Connecting QuickBooks

1. Start the application: `docker compose up`
2. Log in at `{BASE_URL}/login` (Google OAuth)
3. Navigate to `/admin/companies`
4. Click "Connect QuickBooks"
5. Authorize access on Intuit consent screen
6. Company appears in list with "Active" status

### Token Management

- **Automatic Refresh:** Tokens automatically refresh 5 minutes before expiration
- **Manual Refresh:** Click "Refresh" button on companies page
- **Disconnect:** Click "Disconnect" to revoke access (per OAuth 2.0 RFC 7009)
- **Status Indicators:**
  - Green "Active": Token valid for 30+ minutes
  - Yellow "Expiring Soon": Token expires within 30 minutes
  - Red "Expired": Token has expired (automatic refresh will attempt on next API call)
  - Gray "Disconnected": No active connection
```

**Acceptance Criteria:**
- [ ] AC13: README updated with QBO OAuth setup instructions
- [ ] AC13: Clear step-by-step guide using BASE_URL
- [ ] AC13: No hardcoded port numbers

---

### T3.3: Manual E2E Test - OAuth Connect Flow

**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Test Steps:**
- [ ] Start application with `docker compose up`
- [ ] Navigate to `{BASE_URL}/admin/companies`
- [ ] Click "Connect QuickBooks"
- [ ] Log in to QBO if prompted
- [ ] Approve access on consent screen
- [ ] Verify redirect to /admin/companies with success message
- [ ] Verify company appears in list with "Active" status

**Database Verification:**
```bash
sqlite3 data/fortium-qbo.db "SELECT name, code, realm_id, token_status FROM qbo_companies;"
# Expected: Fortium Partners|FOR-XXX|1208415120|active
```

---

### T3.4: Manual E2E Test - Token Refresh

**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Manual Refresh Test:**
- [ ] Click "Refresh" button for connected company
- [ ] Verify success message displayed
- [ ] Verify token_expires_at updated (should be ~1 hour from now)
- [ ] Verify last_refreshed_at updated

**Automatic Refresh Test:**
```bash
# Set token to expire in 3 minutes
sqlite3 data/fortium-qbo.db "UPDATE qbo_companies SET token_expires_at = datetime('now', '+3 minutes') WHERE id=1;"
```
- [ ] Make API request to /api/invoices?company_id=1
- [ ] Verify token was auto-refreshed (token_expires_at should be ~1 hour from now)

---

### T3.5: Manual E2E Test - Disconnect Flow

**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Test Steps:**
- [ ] Click "Disconnect" button for connected company
- [ ] Confirm disconnect in browser dialog
- [ ] Verify success message displayed
- [ ] Verify company shows "Disconnected" status

**Database Verification:**
```bash
sqlite3 data/fortium-qbo.db "SELECT token_status, access_token IS NULL as token_cleared FROM qbo_companies WHERE id=1;"
# Expected: disconnected|1
```

- [ ] Verify API requests to that company fail with clear error message

---

### T3.6: Manual E2E Test - Error Handling

**Estimated Time:** 1 minute
**Status:** [ ] Not Started

**Unauthenticated Access:**
- [ ] Clear cookies and visit /api/qbo/connect (expect redirect to /login)
- [ ] Clear cookies and visit /admin/companies (expect redirect to /login)

**Invalid State:**
- [ ] Manually navigate to /api/qbo/callback?code=test&state=invalid&realmId=123
- [ ] Expect HTML error page with "Invalid state parameter" message

**Reconnecting Existing Company:**
- [ ] Connect a company via OAuth
- [ ] Click "Connect QuickBooks" again
- [ ] Complete OAuth flow for same company
- [ ] Verify existing record updated (not duplicate created)

**Refreshing Disconnected Company:**
- [ ] Disconnect a company
- [ ] Attempt to refresh via API: `curl -X POST {BASE_URL}/api/qbo/companies/1/refresh -b "auth_session=..."`
- [ ] Expect failure message about reconnecting

---

## File Summary

| File | Action | Est. Lines | Sprint |
|------|--------|------------|--------|
| `app/config.py` | MODIFY | +15 | 1 |
| `app/routers/qbo_oauth.py` | CREATE | ~250 | 1 |
| `app/routers/__init__.py` | MODIFY | +1 | 1 |
| `app/main.py` | MODIFY | +2 | 1 |
| `alembic/versions/xxx_add_realm_id_index.py` | CREATE | ~20 | 1 |
| `app/utils/__init__.py` | CREATE | +1 | 2 |
| `app/utils/token_status.py` | CREATE | ~80 | 2 |
| `app/templates/admin/` | CREATE DIR | - | 2 |
| `app/templates/admin/companies.html` | CREATE | ~150 | 2 |
| `app/routers/pages.py` | MODIFY | +50 | 2 |
| `app/services/qbo_service.py` | MODIFY | +15 | 2 |
| `.env.example` | MODIFY | +15 | 3 |
| `README.md` | MODIFY | +50 | 3 |

**Total New/Modified Lines:** ~650

---

## Quality Requirements

### Security Checklist

- [ ] CSRF state validated in OAuth callback (state parameter)
- [ ] Tokens never logged or exposed in responses
- [ ] All QBO management endpoints require admin authentication
- [ ] Session cookies are HttpOnly and Secure (in production)
- [ ] State parameter uses `secrets.token_urlsafe(32)` (cryptographically secure)
- [ ] Token revocation attempted on disconnect (best effort per RFC 7009)

### Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| OAuth redirect | < 100ms | Local redirect, no external calls |
| Token exchange | < 5s | Intuit API dependent |
| Company info fetch | < 2s | Single QBO API call |
| Companies page load | < 500ms | Database query with index on realm_id/code |
| Token refresh | < 2s | Single Intuit API call |

### Error Handling Matrix

| Error Scenario | HTTP Status | Response Type | User Message |
|----------------|-------------|---------------|--------------|
| QBO not configured | 400 | HTML | "QBO OAuth not configured. Set QBO_CLIENT_ID and QBO_CLIENT_SECRET..." |
| Invalid state | 400 | HTML | "Invalid state parameter. Please try again." |
| Missing auth code | 400 | HTML | "Authorization code missing. Please try again." |
| Token exchange fail | 400 | HTML | "Unable to exchange authorization code. Please try again." |
| Company not found | 302 | Redirect | Redirect to /admin/companies with error |
| Refresh token expired | 200 | JSON | {"success": false, "message": "Refresh token expired...", "reconnect_required": true} |
| Unauthenticated | 302 | Redirect | Redirect to /login |

---

## Acceptance Criteria Traceability

| PRD AC | TRD Task | Implementation | Status |
|--------|----------|----------------|--------|
| AC1 | T1.1 | `qbo_callback_url` and `qbo_configured` properties | [ ] |
| AC2 | T1.3 | `GET /api/qbo/connect` endpoint | [ ] |
| AC3 | T1.4 | `GET /api/qbo/callback` endpoint | [ ] |
| AC4 | T1.4 | `_error_response()` helper function (HTML pages) | [ ] |
| AC5 | T2.2, T2.3 | Companies page template and route | [ ] |
| AC6 | T2.1, T2.2 | Token status utility and badge display | [ ] |
| AC7 | T2.4 | `POST /companies/{id}/disconnect` endpoint (with RFC 7009 revocation) | [ ] |
| AC8 | T2.5 | `POST /companies/{id}/refresh` endpoint | [ ] |
| AC9 | - | Already in QBOService._refresh_token() | [x] |
| AC10 | T1.6 | Router registration in main.py | [ ] |
| AC11 | T1.2, T2.3 | `_require_auth()` dependency | [ ] |
| AC12 | T3.1 | .env.example updates (BASE_URL, no hardcoded ports) | [ ] |
| AC13 | T3.2 | README updates (BASE_URL, no hardcoded ports) | [ ] |

---

## Dependencies

### External Dependencies (Already Present)

| Package | Purpose | Version |
|---------|---------|---------|
| `intuitlib` | Intuit OAuth client | Installed |
| `httpx` | Async HTTP for Company Info API | Installed |
| `python-quickbooks` | QBO SDK | Installed |
| `itsdangerous` | Session token signing | Installed |

### Internal Dependencies

| Component | Purpose | Status |
|-----------|---------|--------|
| SessionMiddleware | OAuth state storage | Complete (Phase 2) |
| verify_session() | Admin authentication | Complete (Phase 2) |
| QboCompany model | Token storage | Complete (Phase 1) |
| QBOService._refresh_token() | Auto token refresh | Complete (Phase 1) |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Intuit API rate limiting | Low | Medium | Implement retry with backoff in future |
| OAuth token revocation by user | Medium | Low | Clear error message, easy reconnect flow |
| State parameter collision | Very Low | Medium | Use cryptographically secure random |
| Database token exposure | Low | High | Never log tokens, use SecretStr |
| Session hijacking | Low | High | Signed cookies, HTTPS in production |

---

## Definition of Done

### Code Complete
- [ ] All 19 tasks marked complete
- [ ] All files created/modified as specified
- [ ] No linting errors
- [ ] Type hints on all new functions

### Testing Complete
- [ ] All manual E2E tests pass (T3.3 - T3.6)
- [ ] OAuth connect flow works end-to-end
- [ ] Token refresh works (manual and automatic)
- [ ] Disconnect clears tokens correctly
- [ ] Error scenarios handled gracefully

### Documentation Complete
- [ ] .env.example updated (with BASE_URL pattern)
- [ ] README.md updated with setup instructions
- [ ] Code comments on complex logic

### Ready for Merge
- [ ] PR created with conventional commit title
- [ ] All acceptance criteria verified
- [ ] No security vulnerabilities introduced

---

## Appendix

### Intuit OAuth Endpoints Reference

| Purpose | URL |
|---------|-----|
| Authorization | https://appcenter.intuit.com/connect/oauth2 |
| Token Exchange | https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer |
| Token Revoke | https://developer.api.intuit.com/v2/oauth2/tokens/revoke |
| Company Info | https://quickbooks.api.intuit.com/v3/company/{realmId}/companyinfo/{realmId} |

### Migration from .env Tokens

If existing QBO tokens exist in `.env`:
1. Start application
2. Navigate to `/admin/companies`
3. Click "Connect QuickBooks"
4. Complete OAuth flow
5. Tokens now stored in database
6. Remove `QBO_ACCESS_TOKEN`, `QBO_REFRESH_TOKEN`, `QBO_COMPANY_ID` from `.env`

### Related Documents

- [Phase 1 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
- [Phase 2 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-82-phase2-admin-authentication.md)
- [Phase 3 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-83-phase3-qbo-oauth.md)
- [Linear Issue FOR-83](https://linear.app/fortiumpartners/issue/FOR-83/phase-3-qbo-oauth-token-management)
