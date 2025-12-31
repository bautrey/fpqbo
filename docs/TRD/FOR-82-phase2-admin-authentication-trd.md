# TRD: Phase 2 - Admin Authentication

**Issue:** [FOR-82](https://linear.app/fortiumpartners/issue/FOR-82/phase-2-admin-authentication)
**Project:** fortium-qbo
**PRD:** [FOR-82 Phase 2 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-82-phase2-admin-authentication.md)
**Status:** Ready for Implementation
**Created:** 2025-12-18
**Version:** 1.2

---

## Execution Workflow

```bash
# Step 1: Implement all tasks in this TRD
/agent-os:implement-tasks docs/TRD/FOR-82-phase2-admin-authentication-trd.md

# Step 2: Verify all verification gates pass (T1.0, T2.0, T3.0, T4.0, T5.0)

# Step 3: Create git commit for Phase 2 completion
git add .
git commit -m "feat: implement Phase 2 admin authentication for fortium-qbo

- Google OAuth 2.0 authentication flow (login, callback, logout)
- Session management with signed cookies (itsdangerous)
- Initial admin seeding from INITIAL_ADMIN_EMAIL
- Login page template with Google Sign-In button
- Authenticated home page at root route
- Domain validation and allowlist enforcement
- Authentication dependencies for future phases

Implements FOR-82"
```

---

## Technical Context

### Reference Patterns

This implementation follows proven patterns from existing projects:

| Component | Reference Pattern | Key Patterns |
|-----------|------------------|--------------|
| **Session Management** | itsdangerous library | `URLSafeTimedSerializer` for signed cookies, stateless sessions |
| **OAuth Client** | authlib documentation | `authlib.integrations.starlette_client.OAuth` for Google OAuth |
| **Config Pattern** | Phase 1 `app/config.py` | Already has all Google OAuth settings + `session_max_age_seconds` computed property |
| **Template Pattern** | `pipelinemgr/templates/base.html` | Bootstrap 5, Jinja2 inheritance |
| **Router Pattern** | FastAPI docs + pipelinemgr | Thin controllers, business logic in services |

### Technology Stack

- **FastAPI** 0.109.0+ - Web framework (already in Phase 1)
- **Authlib** 1.3.0+ - OAuth 2.0 client library (already in Phase 1 requirements.txt)
- **itsdangerous** 2.1.0+ - Signed cookie implementation (already in Phase 1)
- **Jinja2** 3.1.0+ - Template engine (already in Phase 1)
- **Bootstrap 5** - Frontend framework (CDN)
- **httpx** 0.26.0+ - Async HTTP client for Authlib (already in Phase 1)

### Architecture Overview

```
Phase 2 additions to fortium-qbo/:
├── app/
│   ├── services/
│   │   ├── session_service.py    # NEW: Session token creation/verification
│   │   └── oauth_service.py      # NEW: OAuth client initialization
│   ├── routers/
│   │   ├── auth.py               # NEW: /auth/login, /auth/callback, /auth/logout
│   │   └── pages.py              # NEW: /login (template), / (home page)
│   ├── templates/
│   │   ├── base.html             # NEW: Bootstrap 5 base template
│   │   ├── login.html            # NEW: Google Sign-In page
│   │   └── home.html             # NEW: Authenticated landing page
│   ├── dependencies.py           # UPDATE: Add get_current_admin_user()
│   └── main.py                   # UPDATE: Add router registration, initial admin seeding
├── .env.example                  # UPDATE: Document OAuth setup
└── README.md                     # UPDATE: Add authentication setup instructions
```

---

## Master Task List

### Phase 1: Session Management Service

**Goal:** Implement stateless signed cookie session management with itsdangerous

- [ ] **T1** - Implement session service
  - [ ] **T1.1** - Create session_service.py with create_session() and verify_session()
  - **Verification Gate:** T1.0 - Verify session creation, verification, and expiration
  - **Git Checkpoint:** After T1.1 completion

### Phase 2: OAuth Service

**Goal:** Implement Google OAuth client initialization with Authlib

- [ ] **T2** - Implement OAuth service
  - [ ] **T2.1** - Create oauth_service.py with get_oauth_client()
  - **Verification Gate:** T2.0 - Verify OAuth client initialization
  - **Git Checkpoint:** After T2.1 completion

### Phase 3: Authentication Router

**Goal:** Implement OAuth flow endpoints (login, callback, logout)

- [ ] **T3** - Implement authentication endpoints
  - [ ] **T3.1** - Create auth.py router with all three endpoints (/auth/login, /auth/callback, /auth/logout)
  - **Verification Gate:** T3.0 - Verify OAuth flow endpoints
  - **Git Checkpoint:** After T3.1 completion

### Phase 4: Templates and Pages Router

**Goal:** Create login UI and authenticated home page

- [ ] **T4** - Implement templates and pages
  - [ ] **T4.1** - Create base.html template with Bootstrap 5
  - [ ] **T4.2** - Create login.html template with Google Sign-In button (extends base.html)
  - [ ] **T4.3** - Create home.html authenticated landing page (extends base.html)
  - [ ] **T4.4** - Create pages.py router with /login and / endpoints
  - **Verification Gate:** T4.0 - Verify templates render and pages work
  - **Git Checkpoint:** After T4.4 completion

### Phase 5: Integration and Dependencies

**Goal:** Wire everything together with main.py updates and dependencies

- [ ] **T5** - Complete integration
  - [ ] **T5.1** - Update dependencies.py with get_current_admin_user()
  - [ ] **T5.2** - Update main.py with router registration
  - [ ] **T5.3** - Update main.py with initial admin seeding in lifespan
  - [ ] **T5.4** - Update .env.example with OAuth documentation
  - [ ] **T5.5** - Update README.md with authentication setup
  - **Verification Gate:** T5.0 - Verify end-to-end OAuth flow
  - **Git Checkpoint:** After T5.5 completion

### Code Review Gate

- [ ] **CR1** - Code review checkpoint
  - [ ] All tasks T1-T5 completed
  - [ ] All verification gates passed
  - [ ] Git checkpoints completed
  - [ ] Code follows reference patterns
  - [ ] No TODO or FIXME comments remain
  - [ ] Manual testing complete

---

## Detailed Task Specifications

### T1: Implement Session Management Service

#### T1.1: Create session_service.py with create_session() and verify_session()

**WHAT:** Create session_service.py with both session creation and verification functions
**HOW:** Use itsdangerous.URLSafeTimedSerializer with app_secret_key
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/services/session_service.py`

> **Note:** `settings.session_max_age_seconds` is a computed `@property` in Phase 1's `config.py` (line 39-42) that returns `session_max_age_days * 24 * 60 * 60`. No changes to config.py required.

**Content:**
```python
"""Session management service using signed cookies."""

from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings


def _get_serializer() -> URLSafeTimedSerializer:
    """Get URLSafeTimedSerializer instance with app secret key."""
    return URLSafeTimedSerializer(settings.app_secret_key.get_secret_value())


def create_session(email: str) -> str:
    """
    Create a signed session token for the given email.

    Args:
        email: User email address to encode in session

    Returns:
        Signed session token string

    Example:
        >>> token = create_session("burke@fortiumpartners.com")
        >>> len(token) > 20
        True
    """
    serializer = _get_serializer()
    return serializer.dumps(email, salt="session")


def verify_session(token: str) -> Optional[str]:
    """
    Verify a session token and extract the email.

    Args:
        token: Signed session token to verify

    Returns:
        Email if token is valid and not expired, None otherwise

    Example:
        >>> token = create_session("burke@fortiumpartners.com")
        >>> email = verify_session(token)
        >>> email
        'burke@fortiumpartners.com'
        >>> verify_session("invalid-token")
        None
    """
    serializer = _get_serializer()
    try:
        email = serializer.loads(
            token,
            salt="session",
            max_age=settings.session_max_age_seconds,
        )
        return email
    except (BadSignature, SignatureExpired):
        return None
```

**Success Criteria:**
- create_session() returns signed token string
- verify_session() validates token signature and expiration
- Expired tokens return None
- Invalid tokens return None
- Token signed with app_secret_key from settings

---

#### T1.0: Verification Gate - Session Creation, Verification, and Expiration

**WHAT:** Verify session token creation, verification, and security features work correctly
**HOW:** Test session creation, verification, expiration, and tampering resistance
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Test session service
python3 << 'PYEOF'
from app.services.session_service import create_session, verify_session

# Test valid session creation and verification
token = create_session("burke@fortiumpartners.com")
assert token
assert len(token) > 20
print(f"✓ Session token created: {token[:20]}...")

# Test valid token verification
email = verify_session(token)
assert email == "burke@fortiumpartners.com"
print(f"✓ Valid token verified: {email}")

# Test invalid token
bad_email = verify_session("invalid-token-string")
assert bad_email is None
print("✓ Invalid token rejected")

# Test tampered token
tampered = token[:-5] + "xxxxx"
tampered_email = verify_session(tampered)
assert tampered_email is None
print("✓ Tampered token rejected")

print("\n✅ All session service tests passed")
PYEOF
```

**Success Criteria:**
- Session token created successfully
- Valid token verified and email extracted
- Invalid token returns None
- Tampered token returns None
- All success messages printed

---

### T2: Implement OAuth Service

#### T2.1: Create oauth_service.py with get_oauth_client()

**WHAT:** Create oauth_service.py with Authlib OAuth client initialization
**HOW:** Use authlib.integrations.starlette_client.OAuth with Google configuration
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/services/oauth_service.py`

**Content:**
```python
"""OAuth service for Google authentication."""

from authlib.integrations.starlette_client import OAuth

from app.config import settings

# Initialize OAuth registry
oauth = OAuth()


def get_oauth_client() -> OAuth:
    """
    Get configured OAuth client with Google provider.

    Configures Google OAuth with:
    - Client ID and secret from settings
    - OpenID Connect discovery for automatic endpoint configuration
    - Scopes: openid email profile
    - Redirect URI: {base_url}/auth/callback

    Returns:
        Configured OAuth instance with Google provider

    Example:
        >>> oauth_client = get_oauth_client()
        >>> oauth_client.google
        <OAuth2Session ...>
    """
    # Register Google OAuth provider (only once)
    if not hasattr(oauth, "google"):
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
            },
        )

    return oauth
```

**Success Criteria:**
- OAuth client registered with Google provider
- Client ID and secret from settings
- OpenID Connect discovery URL configured
- Scopes include openid, email, profile
- Singleton pattern (register only once)

---

#### T2.0: Verification Gate - OAuth Client Initialization

**WHAT:** Verify OAuth client initializes with Google provider correctly
**HOW:** Import oauth service and verify Google provider registered
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Test OAuth service
python3 << 'PYEOF'
from app.services.oauth_service import get_oauth_client

# Get OAuth client
oauth_client = get_oauth_client()
assert oauth_client
print("✓ OAuth client initialized")

# Verify Google provider registered
assert hasattr(oauth_client, "google")
print("✓ Google provider registered")

# Verify configuration
google = oauth_client.google
assert google.client_id
assert google.client_secret
print("✓ Google OAuth configured with credentials")

print("\n✅ All OAuth service tests passed")
PYEOF
```

**Success Criteria:**
- OAuth client initializes successfully
- Google provider accessible via oauth.google
- Client ID and secret configured
- All success messages printed

---

### T3: Implement Authentication Router

#### T3.1: Create auth.py router with all three endpoints

**WHAT:** Create complete auth.py router file with /auth/login, /auth/callback, and /auth/logout
**HOW:** Use oauth.google.authorize_redirect() for login, token exchange for callback, cookie clearing for logout
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/routers/auth.py`

**Content:**
```python
"""Authentication router for Google OAuth flow."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AdminUser
from app.services.oauth_service import get_oauth_client
from app.services.session_service import create_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """
    Initiate Google OAuth flow.

    Redirects user to Google OAuth consent screen with:
    - State parameter for CSRF protection (Authlib automatic)
    - Redirect URI: {base_url}/auth/callback
    - Scopes: openid email profile

    Returns:
        Redirect to Google OAuth authorization URL
    """
    oauth = get_oauth_client()
    redirect_uri = f"{settings.base_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """
    Handle OAuth callback from Google.

    Validation flow:
    1. Exchange authorization code for access token (Authlib validates state)
    2. Validate email domain matches settings.google_allowed_domain
    3. Check if user exists in admin_users table
    4. Create session cookie with signed token
    5. Update last_login_at timestamp
    6. Redirect to / (home page)

    Error handling:
    - Domain mismatch: 400 Bad Request with error message
    - Allowlist failure: 403 Forbidden with error message
    - OAuth error: 400 Bad Request with error message

    Returns:
        Redirect to / with session cookie on success
        HTML error page on failure
    """
    oauth = get_oauth_client()

    try:
        # Exchange authorization code for access token (validates state)
        token = await oauth.google.authorize_access_token(request)

        # Get user info from ID token
        user_info = token.get("userinfo")
        if not user_info:
            logger.error("No userinfo in OAuth token")
            return _error_response(
                "Authentication failed. Please try again or contact your administrator.",
                400
            )

        email = user_info.get("email")
        if not email:
            logger.error("No email in userinfo")
            return _error_response(
                "Authentication failed. Please try again or contact your administrator.",
                400
            )

        logger.info(f"OAuth callback received for email: {email}")

        # Validate domain
        domain = email.split("@")[-1]
        if domain != settings.google_allowed_domain:
            logger.warning(f"Domain validation failed for {email}: {domain} != {settings.google_allowed_domain}")
            return _error_response(
                f"Authentication failed. Only @{settings.google_allowed_domain} emails are allowed.",
                400
            )

        # Check allowlist (admin_users table)
        db = SessionLocal()
        try:
            admin_user = db.execute(
                select(AdminUser).where(AdminUser.email == email)
            ).scalar_one_or_none()

            if not admin_user:
                logger.warning(f"Allowlist validation failed for {email}: user not in admin_users table")
                return _error_response(
                    "User not authorized. Please contact your administrator for access.",
                    403
                )

            # Update last_login_at
            admin_user.last_login_at = datetime.utcnow()
            db.commit()
            logger.info(f"Updated last_login_at for {email}")

        finally:
            db.close()

        # Create session cookie
        session_token = create_session(email)
        logger.info(f"Session created for {email}")

        # Redirect to home with session cookie
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="session",
            value=session_token,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=not settings.debug,  # HTTPS only in production
            samesite="lax",
            path="/",
        )

        return response

    except Exception as e:
        logger.error(f"OAuth callback error: {e}", exc_info=True)
        return _error_response(
            "Authentication failed. Please try again or contact your administrator.",
            400
        )


@router.get("/logout")
async def logout():
    """
    Logout user by clearing session cookie.

    Returns:
        Redirect to /login with cleared session cookie
    """
    response = RedirectResponse(url="/login", status_code=302)
    response.set_cookie(
        key="session",
        value="",
        max_age=0,
        path="/",
    )
    logger.info("User logged out")
    return response


def _error_response(message: str, status_code: int):
    """
    Generate HTML error page.

    Args:
        message: Error message to display
        status_code: HTTP status code

    Returns:
        HTMLResponse with error message
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Authentication Error - fortium-qbo</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="row justify-content-center">
                <div class="col-md-6">
                    <div class="card border-danger">
                        <div class="card-header bg-danger text-white">
                            <h5 class="mb-0">Authentication Error</h5>
                        </div>
                        <div class="card-body">
                            <p class="card-text">{message}</p>
                            <a href="/login" class="btn btn-primary">Back to Login</a>
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

**Success Criteria:**
- All three endpoints implemented in single file
- /auth/login redirects to Google OAuth with state parameter
- /auth/callback validates domain and allowlist, creates session
- /auth/logout clears session cookie
- Error responses use Bootstrap HTML templates
- Proper logging throughout
- datetime import at top of file

---

#### T3.0: Verification Gate - OAuth Flow Endpoints

**WHAT:** Verify all auth endpoints exist and respond correctly
**HOW:** Import router, verify routes registered with correct paths
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Import check
python3 << 'PYEOF'
from app.routers.auth import router

# Verify routes registered
routes = [route.path for route in router.routes]
assert "/login" in routes
assert "/callback" in routes
assert "/logout" in routes
print("✓ All auth routes registered")
print(f"  Routes: {routes}")

# Verify router prefix
assert router.prefix == "/auth"
print("✓ Router has /auth prefix")

print("\n✅ Auth router verification passed")
PYEOF
```

**Success Criteria:**
- All three routes registered (/login, /callback, /logout)
- Router uses /auth prefix
- Routes accessible via router.routes
- All success messages printed

---

### T4: Implement Templates and Pages Router

#### T4.1: Create base.html template with Bootstrap 5

**WHAT:** Create base.html template with Bootstrap 5 following pipelinemgr pattern
**HOW:** Use Bootstrap 5 CDN, Jinja2 blocks for title/content
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/templates/base.html`

**Content:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}fortium-qbo{% endblock %}</title>

    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- Bootstrap Icons -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">

    {% block extra_css %}{% endblock %}
</head>
<body>
    <!-- Main Content -->
    <main class="container">
        {% block content %}{% endblock %}
    </main>

    <!-- Bootstrap JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

    {% block extra_js %}{% endblock %}
</body>
</html>
```

**Success Criteria:**
- Bootstrap 5 CSS from CDN
- Bootstrap Icons included
- Jinja2 blocks for title, content, extra_css, extra_js
- Minimal design (no navbar for auth pages)
- Follows pipelinemgr pattern

---

#### T4.2: Create login.html template with Google Sign-In button

**WHAT:** Create login.html template with Google Sign-In button
**HOW:** Extend base.html, Bootstrap card layout, link to /auth/login
**TOOL:** Write
**DEPENDS ON:** T4.1 (base.html must exist)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/templates/login.html`

**Content:**
```html
{% extends "base.html" %}

{% block title %}Login - fortium-qbo{% endblock %}

{% block content %}
<div class="row justify-content-center" style="margin-top: 100px;">
    <div class="col-md-4">
        <div class="card shadow">
            <div class="card-body text-center p-5">
                <h3 class="card-title mb-4">fortium-qbo Admin</h3>
                <p class="text-muted mb-4">Sign in with your Fortium Partners Google account</p>

                <a href="/auth/login" class="btn btn-outline-secondary btn-lg d-flex align-items-center justify-content-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 48 48" class="me-2">
                        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                    </svg>
                    Sign in with Google
                </a>

                <p class="text-muted small mt-4 mb-0">Only @fortiumpartners.com accounts are authorized</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

**Success Criteria:**
- Extends base.html template
- Centered card layout with Bootstrap
- Google logo SVG included
- Button links to /auth/login
- Domain restriction message displayed
- Clean, professional design

---

#### T4.3: Create home.html authenticated landing page

**WHAT:** Create home.html template for authenticated users
**HOW:** Extend base.html, display user email, logout button
**TOOL:** Write
**DEPENDS ON:** T4.1 (base.html must exist)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/templates/home.html`

**Content:**
```html
{% extends "base.html" %}

{% block title %}Home - fortium-qbo{% endblock %}

{% block content %}
<div class="row justify-content-center" style="margin-top: 100px;">
    <div class="col-md-6">
        <div class="card shadow">
            <div class="card-body text-center p-5">
                <h4 class="card-title mb-4">Welcome to fortium-qbo</h4>
                <p class="card-text">You are authenticated as:</p>
                <p class="fw-bold fs-5">{{ user.email }}</p>
                <hr class="my-4">
                <p class="text-muted small mb-4">Admin features coming in Phase 3+</p>
                <a href="/auth/logout" class="btn btn-outline-secondary">
                    <i class="bi bi-box-arrow-right me-2"></i>Logout
                </a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

**Success Criteria:**
- Extends base.html template
- Displays user.email passed from context
- Logout button links to /auth/logout
- Bootstrap Icons used for logout icon
- Clean, centered design
- Message about future admin features

---

#### T4.4: Create pages.py router with /login and / endpoints

**WHAT:** Create pages.py router with template rendering endpoints
**HOW:** Use Jinja2Templates, implement /login (public) and / (authenticated)
**TOOL:** Write

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/routers/pages.py`

**Content:**
```python
"""Pages router for HTML template rendering."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AdminUser
from app.services.session_service import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pages"])

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
async def login_page(request: Request):
    """
    Render login page with Google Sign-In button.

    Public endpoint - no authentication required.

    Returns:
        HTML login page template
    """
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/")
async def home_page(request: Request):
    """
    Render authenticated home page.

    Checks for valid session cookie:
    - If authenticated: Show home page with user email
    - If not authenticated: Redirect to /login

    Returns:
        HTML home page if authenticated
        Redirect to /login if not authenticated
    """
    # Check for session cookie
    session_token = request.cookies.get("session")

    if not session_token:
        logger.info("No session cookie, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Verify session
    email = verify_session(session_token)

    if not email:
        logger.info("Invalid session token, redirecting to login")
        return RedirectResponse(url="/login", status_code=302)

    # Get user from database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()

        if not admin_user:
            logger.warning(f"Session valid but user not in database: {email}")
            return RedirectResponse(url="/login", status_code=302)

        # Render home page with user context
        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "user": admin_user,
            }
        )

    finally:
        db.close()
```

**Success Criteria:**
- Jinja2Templates configured with app/templates directory
- /login endpoint renders login.html (public)
- / endpoint checks session cookie
- / redirects to /login if not authenticated
- / renders home.html with user context if authenticated
- Router has no prefix (root level routes)

---

#### T4.0: Verification Gate - Templates Render and Pages Work

**WHAT:** Verify templates exist and pages router works
**HOW:** Test template imports, router registration, page logic
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Verify templates exist
ls -la app/templates/
echo "✓ Templates directory exists"

test -f app/templates/base.html && echo "✓ base.html exists"
test -f app/templates/login.html && echo "✓ login.html exists"
test -f app/templates/home.html && echo "✓ home.html exists"

# Verify pages router
python3 << 'PYEOF'
from app.routers.pages import router, templates

# Verify routes
routes = [route.path for route in router.routes]
assert "/" in routes
assert "/login" in routes
print("✓ Page routes registered")
print(f"  Routes: {routes}")

# Verify templates configured
assert templates.env.loader
print("✓ Jinja2Templates configured")

print("\n✅ Templates and pages router verification passed")
PYEOF
```

**Success Criteria:**
- All 3 template files exist
- Router has / and /login routes
- Jinja2Templates configured
- All success messages printed

---

### T5: Complete Integration

#### T5.1: Update dependencies.py with get_current_admin_user()

**WHAT:** Add get_current_admin_user() dependency function for future phases
**HOW:** Extract session from cookie, verify, lookup user in database
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/dependencies.py`

**REPLACE entire file with (includes existing get_db plus new get_current_admin_user):**

> **Note:** Phase 1 dependencies.py only exports `get_db`. This replacement preserves that export while adding the new authentication dependency.

```python
"""Shared dependencies for FastAPI dependency injection."""

from typing import Optional

from fastapi import Request
from sqlalchemy import select

from app.database import SessionLocal, get_db
from app.models import AdminUser
from app.services.session_service import verify_session

__all__ = ["get_db", "get_current_admin_user"]


async def get_current_admin_user(request: Request) -> Optional[AdminUser]:
    """
    Get current authenticated admin user from session cookie.

    Extracts session cookie, verifies token, and looks up user in database.
    Returns None if not authenticated or user not found.

    This dependency is for future phases when protecting admin routes.

    Args:
        request: FastAPI request object

    Returns:
        AdminUser object if authenticated and valid, None otherwise

    Example usage:
        @app.get("/admin/dashboard")
        async def dashboard(user: AdminUser = Depends(get_current_admin_user)):
            if not user:
                raise HTTPException(401, "Not authenticated")
            return {"email": user.email}
    """
    # Extract session cookie
    session_token = request.cookies.get("session")
    if not session_token:
        return None

    # Verify session token
    email = verify_session(session_token)
    if not email:
        return None

    # Look up user in database
    db = SessionLocal()
    try:
        admin_user = db.execute(
            select(AdminUser).where(AdminUser.email == email)
        ).scalar_one_or_none()
        return admin_user
    finally:
        db.close()
```

**Success Criteria:**
- get_current_admin_user() function added
- Returns AdminUser or None
- Verifies session and looks up in database
- Added to __all__ exports
- get_db preserved from Phase 1

---

#### T5.2: Update main.py with router registration

**WHAT:** Register auth and pages routers in main.py
**HOW:** Import routers and use app.include_router()
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/main.py`

**Add after imports:**
```python
from app.routers import auth, pages
```

**Add after app creation (after `app = FastAPI(...)`, before static files mount):**
```python
# Include routers
app.include_router(auth.router)
app.include_router(pages.router)
```

**Success Criteria:**
- auth and pages routers imported
- Both routers registered with app.include_router()
- Routers added after app creation, before static files mount

---

#### T5.3: Update main.py with initial admin seeding in lifespan

**WHAT:** Add initial admin user seeding to lifespan startup
**HOW:** Check INITIAL_ADMIN_EMAIL, create admin_users entry if not exists
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/app/main.py`

**Update lifespan function to add admin seeding after startup logging:**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown events.

    Startup:
    - Log application start
    - Seed initial admin user if INITIAL_ADMIN_EMAIL is configured

    Shutdown:
    - Log application shutdown
    """
    # Startup
    logger.info("fortium-qbo starting up...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")

    # Seed initial admin user
    if settings.initial_admin_email:
        from datetime import datetime
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models import AdminUser

        db = SessionLocal()
        try:
            # Check if user already exists
            existing_user = db.execute(
                select(AdminUser).where(AdminUser.email == settings.initial_admin_email)
            ).scalar_one_or_none()

            if existing_user:
                logger.info(f"Initial admin user already exists: {settings.initial_admin_email}")
            else:
                # Create initial admin user
                admin_user = AdminUser(
                    email=settings.initial_admin_email,
                    is_super_admin=True,
                    created_at=datetime.utcnow(),
                )
                db.add(admin_user)
                db.commit()
                logger.info(f"Created initial admin user: {settings.initial_admin_email}")

        except Exception as e:
            logger.error(f"Failed to seed initial admin user: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    else:
        logger.info("No INITIAL_ADMIN_EMAIL configured, skipping admin seeding")

    yield

    # Shutdown
    logger.info("fortium-qbo shutting down...")
```

**Success Criteria:**
- Initial admin seeding logic added to lifespan startup
- Checks if INITIAL_ADMIN_EMAIL is configured
- Creates AdminUser with is_super_admin=True if not exists
- Logs creation or existence
- Error handling with rollback on failure
- Does not prevent startup on errors

---

#### T5.4: Update .env.example with OAuth documentation

**WHAT:** Enhance .env.example with OAuth setup instructions
**HOW:** Add detailed comments about Google OAuth configuration
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/.env.example`

**Update Google OAuth section to match PRD AC13:**

```bash
# Google OAuth (Admin UI) - REQUIRED
# 1. Create OAuth 2.0 Client ID in Google Cloud Console:
#    https://console.cloud.google.com/apis/credentials
# 2. Configure authorized redirect URIs:
#    - Local: http://localhost:8000/auth/callback
#    - Production: https://your-domain.com/auth/callback
# 3. Copy Client ID and Client Secret below
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Google OAuth (Optional)
# Restrict authentication to specific domain (default: fortiumpartners.com)
GOOGLE_ALLOWED_DOMAIN=fortiumpartners.com

# Initial admin user (will be created with is_super_admin=True on first startup)
# Leave empty to skip initial admin seeding
INITIAL_ADMIN_EMAIL=burke@fortiumpartners.com
```

**Success Criteria:**
- Detailed OAuth setup instructions added
- Step-by-step guide with URLs
- Redirect URI examples for local and production
- Clear explanation of optional settings

---

#### T5.5: Update README.md with authentication setup

**WHAT:** Add Authentication Setup section to README
**HOW:** Insert new section after Quick Start with OAuth instructions
**TOOL:** Edit (requires Read first)

**File Path:** `/Users/burke/projects/fpqbo/fortium-qbo/README.md`

**Add new section after Quick Start and before Project Structure:**

```markdown
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
```

**Also update Phase Roadmap:**
```markdown
## Phase Roadmap

- ✅ **Phase 1:** Core Infrastructure
- ✅ **Phase 2:** Admin UI - Google OAuth authentication (this phase)
- ⬜ **Phase 3:** QBO OAuth - Token management and refresh
- ⬜ **Phase 4:** API Gateway - API key authentication
- ⬜ **Phase 5:** QBO Proxy - Entity endpoints
- ⬜ **Phase 6:** Deployment - Render production deployment
```

**Success Criteria:**
- Authentication Setup section added
- Step-by-step OAuth configuration guide
- Instructions for initial admin and adding users
- Phase Roadmap updated with Phase 2 complete checkmark

---

#### T5.0: Verification Gate - End-to-End OAuth Flow

**WHAT:** Verify complete OAuth flow works end-to-end
**HOW:** Start server, verify all routes work, check database seeding
**TOOL:** Bash

**Verification Commands:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo

# Verify initial admin seeding (simulation with cleanup)
python3 << 'PYEOF'
import os
os.environ.setdefault('DATABASE_URL', 'sqlite:///./data/fortium-qbo.db')

from datetime import datetime
from sqlalchemy import select
from app.database import SessionLocal
from app.models import AdminUser

# Simulate startup seeding
db = SessionLocal()
try:
    # Use test email to avoid polluting real admin data
    test_email = "test-phase2-verification@fortiumpartners.com"

    # Clean up any existing test user first
    existing_test = db.execute(
        select(AdminUser).where(AdminUser.email == test_email)
    ).scalar_one_or_none()
    if existing_test:
        db.delete(existing_test)
        db.commit()

    # Create test admin user
    admin_user = AdminUser(
        email=test_email,
        is_super_admin=True,
        created_at=datetime.utcnow(),
    )
    db.add(admin_user)
    db.commit()
    print(f"✓ Created test admin user: {test_email}")

    # Verify user in database
    verify_user = db.execute(
        select(AdminUser).where(AdminUser.email == test_email)
    ).scalar_one()

    assert verify_user.email == test_email
    assert verify_user.is_super_admin == True
    print("✓ Admin user verified in database")

    # Cleanup test user
    db.delete(verify_user)
    db.commit()
    print("✓ Test user cleaned up")

finally:
    db.close()

print("\n✅ Initial admin seeding verification passed")
PYEOF

# Verify all routers registered
python3 << 'PYEOF'
from app.main import app

# Get all routes
routes = [(route.path, list(route.methods) if hasattr(route, 'methods') else []) for route in app.routes if hasattr(route, 'path')]

# Expected routes
expected = [
    ("/", ["GET"]),
    ("/login", ["GET"]),
    ("/auth/login", ["GET"]),
    ("/auth/callback", ["GET"]),
    ("/auth/logout", ["GET"]),
    ("/health", ["GET"]),
]

for path, methods in expected:
    route_found = any(r[0] == path and any(m in r[1] for m in methods) for r in routes)
    if not route_found:
        print(f"✗ Route {path} {methods} not found")
        print(f"Available routes: {routes}")
        raise AssertionError(f"Route {path} not found")
    print(f"✓ Route registered: {path} {methods}")

print("\n✅ All routes registered successfully")
PYEOF

# Verify dependencies
python3 << 'PYEOF'
from app.dependencies import get_current_admin_user, get_db

assert callable(get_current_admin_user)
assert callable(get_db)
print("✓ Authentication dependencies available")

print("\n✅ All dependencies verification passed")
PYEOF

echo ""
echo "✅ Phase 2 integration verification complete"
echo ""
echo "Manual testing required:"
echo "1. Start server: uvicorn app.main:app --reload --port 8000"
echo "2. Visit http://localhost:8000/login"
echo "3. Click 'Sign in with Google'"
echo "4. Complete OAuth flow (requires valid Google OAuth credentials)"
echo "5. Verify redirect to / (home page)"
echo "6. Verify user email displayed on home page"
echo "7. Click 'Logout' and verify redirect to /login"
```

**Success Criteria:**
- Initial admin seeding works with cleanup (no pollution)
- All routes registered (/, /login, /auth/*)
- Dependencies available
- All automated tests pass
- Manual testing checklist provided

---

## Code Review Checklist

### CR1: Code Review Checkpoint

**Purpose:** Ensure all Phase 2 tasks meet quality standards before git commit

#### Completeness
- [ ] All tasks T1-T5 completed with checkboxes marked
- [ ] All verification gates (T1.0, T2.0, T3.0, T4.0, T5.0) passed
- [ ] All git checkpoints identified for manual commits

#### Code Quality
- [ ] Session service uses itsdangerous URLSafeTimedSerializer
- [ ] OAuth service uses Authlib with proper configuration
- [ ] Auth router follows FastAPI patterns
- [ ] All endpoints have proper logging
- [ ] Error responses include user-friendly messages
- [ ] Type hints present on all functions
- [ ] Docstrings present on all functions
- [ ] datetime imported at top of auth.py (not inline)

#### Security
- [ ] Session cookies use HttpOnly flag
- [ ] Secure flag enabled in production (not debug)
- [ ] SameSite=Lax for CSRF protection
- [ ] Session tokens signed with app_secret_key
- [ ] OAuth state parameter validated (Authlib automatic)
- [ ] Domain validation enforced
- [ ] Allowlist validation enforced
- [ ] No secrets in code or logs

#### Templates
- [ ] base.html uses Bootstrap 5 CDN
- [ ] login.html has Google Sign-In button
- [ ] home.html shows user email and logout button
- [ ] All templates extend base.html
- [ ] Responsive design (mobile-friendly)

#### Integration
- [ ] Initial admin seeding in lifespan works
- [ ] Routers registered in main.py
- [ ] get_current_admin_user dependency added
- [ ] .env.example has OAuth documentation
- [ ] README has authentication setup section

#### Database
- [ ] Initial admin created with is_super_admin=True
- [ ] last_login_at updated on successful login
- [ ] Database queries use proper session management
- [ ] No database connection leaks

#### Testing
- [ ] Can import session_service and oauth_service
- [ ] Session token creation and verification works
- [ ] OAuth client initializes correctly
- [ ] All routes registered
- [ ] Templates render without errors
- [ ] Initial admin seeding works with cleanup

---

## Success Criteria Summary

Phase 2 is complete when:

1. **Session Service** - create_session() and verify_session() work (AC2)
2. **OAuth Service** - get_oauth_client() initializes Google provider (AC3)
3. **Auth Endpoints** - /auth/login, /auth/callback, /auth/logout implemented (AC5, AC6, AC7)
4. **Templates** - base.html, login.html and home.html created (AC8, AC9)
5. **Pages Router** - /login and / endpoints work (AC8, AC9)
6. **Initial Admin** - INITIAL_ADMIN_EMAIL seeded on startup (AC4)
7. **Dependencies** - get_current_admin_user() for future phases (AC10)
8. **Router Registration** - Auth and pages routers registered in main.py (AC11)
9. **Documentation** - .env.example and README updated (AC13, AC14)

All verification gates must pass, code review checklist complete, and manual OAuth flow tested.

---

## Appendix

### Git Checkpoints

Recommended git commits after each major phase:

```bash
# After T1.1 - Session service complete
git add app/services/session_service.py
git commit -m "feat: implement session management with itsdangerous"

# After T2.1 - OAuth service complete
git add app/services/oauth_service.py
git commit -m "feat: implement Google OAuth service with Authlib"

# After T3.1 - Auth router complete
git add app/routers/auth.py
git commit -m "feat: implement OAuth endpoints (login, callback, logout)"

# After T4.4 - Templates and pages complete
git add app/templates/ app/routers/pages.py
git commit -m "feat: implement login page and authenticated home page"

# After T5.5 - Integration complete
git add app/dependencies.py app/main.py .env.example README.md
git commit -m "feat: complete Phase 2 admin authentication integration"

# Final commit after all verification gates pass
git add .
git commit -m "feat: implement Phase 2 admin authentication for fortium-qbo

- Google OAuth 2.0 authentication flow (login, callback, logout)
- Session management with signed cookies (itsdangerous)
- Initial admin seeding from INITIAL_ADMIN_EMAIL
- Login page template with Google Sign-In button
- Authenticated home page at root route
- Domain validation and allowlist enforcement
- Authentication dependencies for future phases

Implements FOR-82"
```

### Related Documents

- [PRD: Phase 2](/Users/burke/projects/fpqbo/docs/PRD/FOR-82-phase2-admin-authentication.md)
- [TRD: Phase 1](/Users/burke/projects/fpqbo/docs/TRD/FOR-81-phase1-core-infrastructure-trd.md)
- [Design Document](/Users/burke/projects/fpqbo/docs/plans/2025-12-17-fortium-qbo-design.md)
- [Linear Issue FOR-82](https://linear.app/fortiumpartners/issue/FOR-82/phase-2-admin-authentication)

### Dependencies from Phase 1

Phase 2 requires these Phase 1 components:

- **app/config.py** - Google OAuth settings (google_client_id, google_client_secret, google_allowed_domain, initial_admin_email, app_secret_key, base_url)
- **app/models/admin_user.py** - AdminUser model for allowlist
- **app/database.py** - Database session management
- **app/main.py** - FastAPI app with lifespan context manager
- **requirements.txt** - authlib, itsdangerous, httpx already included

All Phase 1 components are complete and tested.

### OAuth Flow Diagram

```
User visits / (root)
  ↓
Check session cookie
  ↓
No session? → Redirect to /login
  ↓
Login page: Click "Sign in with Google"
  ↓
/auth/login → Redirect to Google OAuth
  ↓
Google OAuth consent screen
  ↓
User approves
  ↓
Google redirects to /auth/callback?code=xxx&state=yyy
  ↓
Exchange code for token (Authlib validates state)
  ↓
Validate email domain (@fortiumpartners.com)
  ↓
Check admin_users allowlist
  ↓
Create signed session cookie
  ↓
Update last_login_at
  ↓
Redirect to / with session cookie
  ↓
/ (root) verifies session → Render home.html
  ↓
Home page shows user email + logout button
  ↓
Click logout → /auth/logout
  ↓
Clear session cookie
  ↓
Redirect to /login
```

### Security Considerations

1. **Session Security:**
   - Signed cookies prevent tampering (itsdangerous)
   - HttpOnly flag prevents XSS access to cookies
   - Secure flag enforces HTTPS (production only)
   - SameSite=Lax prevents CSRF attacks
   - Configurable expiration (default 30 days)
   - Stateless sessions (no server-side storage needed)

2. **OAuth Security:**
   - State parameter prevents CSRF on OAuth flow (Authlib automatic)
   - Tokens validated before creating session
   - Domain validation prevents unauthorized email domains
   - Allowlist validation provides defense in depth
   - OAuth tokens discarded after session creation

3. **Database Security:**
   - Admin emails unique and indexed
   - Email validation at multiple layers
   - Last login tracking for audit trail
   - Super admin flag for future privilege escalation

4. **Error Handling:**
   - OAuth errors logged with details for debugging
   - User-facing errors are generic (no information leakage)
   - Failed auth attempts tracked via request logs

### Manual Testing Checklist

After implementation, perform these manual tests:

1. **Login Flow:**
   - [ ] Visit http://localhost:8000/ → redirects to /login
   - [ ] Click "Sign in with Google" → redirects to Google OAuth
   - [ ] Approve consent → redirects back to /auth/callback
   - [ ] After callback → redirects to / (home page)
   - [ ] Home page displays user email

2. **Session Persistence:**
   - [ ] Refresh page → still authenticated (no redirect to login)
   - [ ] Close browser and reopen → still authenticated (within session max age)
   - [ ] Check cookies in browser DevTools → session cookie present with HttpOnly, Secure, SameSite flags

3. **Logout:**
   - [ ] Click "Logout" button → redirects to /login
   - [ ] Session cookie cleared (max-age=0)
   - [ ] Visit / again → redirects to /login (not authenticated)

4. **Domain Validation:**
   - [ ] Attempt login with personal Gmail account → error page "Only @fortiumpartners.com emails allowed"
   - [ ] Attempt login with other domain → error page with domain restriction

5. **Allowlist Validation:**
   - [ ] Login with @fortiumpartners.com email NOT in admin_users table → error page "User not authorized"
   - [ ] Add user to admin_users table → login succeeds

6. **Initial Admin Seeding:**
   - [ ] Set INITIAL_ADMIN_EMAIL in .env
   - [ ] Start server → logs "Created initial admin user: ..."
   - [ ] Restart server → logs "Initial admin user already exists: ..."
   - [ ] Verify user in database with is_super_admin=True

### Environment Variables Summary

Phase 2 uses these environment variables (all defined in Phase 1 config.py):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| GOOGLE_CLIENT_ID | Yes | - | OAuth client ID from Google Cloud Console |
| GOOGLE_CLIENT_SECRET | Yes | - | OAuth client secret |
| GOOGLE_ALLOWED_DOMAIN | No | fortiumpartners.com | Email domain restriction |
| INITIAL_ADMIN_EMAIL | No | None | First admin user to seed on startup |
| APP_SECRET_KEY | Yes | - | Session cookie signing key (min 32 chars) |
| SESSION_MAX_AGE_DAYS | No | 30 | Session cookie expiration |
| BASE_URL | Yes | http://localhost:8000 | OAuth redirect URI base |

### Future Enhancements (Post-Phase 2)

1. **Admin Management UI (Phase 2.5 or Phase 3):**
   - Add/remove admin users via web interface
   - Toggle super_admin status
   - View admin user list with last login times

2. **Protected Routes Middleware:**
   - Decorator for route protection
   - Automatic redirect to /login for unauthenticated users
   - Role-based access control

3. **Session Improvements:**
   - "Remember me" checkbox (extended session)
   - Concurrent session limits
   - Session invalidation (force logout all sessions)

4. **OAuth Enhancements:**
   - Support multiple OAuth providers (Microsoft, Okta)
   - Profile picture from Google account
   - Additional user metadata

These are explicitly out of scope for Phase 2 but documented for future reference.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-18 | Initial TRD created by tech-lead-orchestrator |
| 1.1 | 2025-12-18 | Refinements: (1) Consolidated T3 into single task for all three endpoints (2) Fixed datetime import placement in auth.py (3) Made template dependencies explicit (4) Enhanced T5.0 verification with cleanup to prevent database pollution (5) Added code review checklist item for datetime import location (6) Clarified authlib already in requirements.txt (7) Improved success criteria throughout |
| 1.2 | 2025-12-18 | QA fixes: (1) Added note that `session_max_age_seconds` is Phase 1 computed property (2) Fixed T5.1 ambiguity - clarified REPLACE entire file vs additive |
