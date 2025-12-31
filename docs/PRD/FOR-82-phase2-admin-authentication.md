# PRD: Phase 2 - Admin Authentication

**Issue:** [FOR-82](https://linear.app/fortiumpartners/issue/FOR-82/phase-2-admin-authentication)
**Project:** fortium-qbo
**Date:** 2025-12-17
**Status:** Ready for TRD
**Version:** 1.1

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2 | 2025-12-17 | Added AC9: Authenticated Home Page - defines root route for post-auth landing (QA feedback) |
| 1.1 | 2025-12-17 | Refined security requirements, added error handling details, clarified template directory, enhanced testing scenarios, added CSRF protection details, fixed endpoint confusion |
| 1.0 | 2025-12-17 | Initial PRD creation |

---

## Product Summary

### Problem Statement

The fortium-qbo admin UI needs secure authentication to protect sensitive QuickBooks data and administrative functions. Currently:
- No authentication mechanism exists for the admin UI
- Admin users cannot log in or be identified
- No session management to maintain authenticated state
- No initial admin user seeding mechanism
- No domain validation or user allowlist enforcement

Without authentication, the admin UI would be completely open, exposing sensitive financial data and API key management to unauthorized access.

### Solution

Implement Google OAuth 2.0 authentication with session management and user allowlist:
1. **Google OAuth flow** - Login, callback, and logout endpoints using Authlib
2. **Session management** - Secure, signed cookies with configurable expiration
3. **User allowlist** - Database-backed admin_users table validation
4. **Domain restriction** - Enforce @fortiumpartners.com domain requirement
5. **Initial admin seeding** - Bootstrap first admin user from INITIAL_ADMIN_EMAIL
6. **Login UI** - Simple HTML login page with Google Sign-In button

### Value Proposition

This phase establishes:
- **Security** - OAuth 2.0 industry-standard authentication
- **Simplicity** - Single Sign-On with existing Google accounts (no password management)
- **Control** - Database allowlist ensures only authorized users access admin UI
- **Auditability** - Track admin user creation and last login times
- **Flexibility** - Super admin designation for future role-based features

---

## User Analysis

### Primary Users

| User Type | Description | Needs |
|-----------|-------------|-------|
| **Admin Users** | Fortium Partners staff managing QBO integration | Secure, simple login with Google accounts |
| **Super Admin** | Initial admin (Burke) who manages other admins | Ability to add/remove admin users (future) |
| **Developer (Burke)** | Implements and maintains system | Clear OAuth patterns following pipelinemgr conventions |

### User Personas

#### Burke (Initial Admin & Developer)
- **Role:** Super admin, primary developer
- **Context:** Uses burke@fortiumpartners.com Google account for everything
- **Pain Points:** Time wasted on complex auth systems, credential management overhead
- **Goals:** Quick Google Sign-In that "just works," minimal configuration

#### Finance Team Member (Future Admin)
- **Role:** Admin user who manages QBO data and API keys
- **Context:** Already uses @fortiumpartners.com Google Workspace account daily
- **Pain Points:** Remembering yet another password, slow manual login processes
- **Goals:** Fast SSO with existing work Google account, no new credentials

### Pain Points Addressed

1. **No secure access control** → Google OAuth with domain validation
2. **No user identification** → Session cookies track authenticated users
3. **Manual admin management** → Database allowlist + initial admin seeding
4. **Credential management burden** → SSO eliminates password requirements

---

## Goals & Non-Goals

### Goals

| Goal | Success Metric |
|------|----------------|
| Implement Google OAuth login flow | `/auth/login` redirects to Google, `/auth/callback` creates session |
| Secure session management | Signed cookies with proper expiration and HttpOnly/Secure flags |
| Admin user validation | Only @fortiumpartners.com users in admin_users table can access UI |
| Initial admin seeding | INITIAL_ADMIN_EMAIL user created on first startup if not exists |
| Login page UI | Simple HTML page with Google Sign-In button |

### Non-Goals (Out of Scope for Phase 2)

- Admin user management UI (add/remove admins) - Future enhancement
- Role-based permissions beyond super_admin flag - Future enhancement
- Password-based authentication - Google OAuth only
- Multi-factor authentication (MFA) - Handled by Google
- API key authentication for admin UI - OAuth only (API keys are for external clients in Phase 4)
- QBO OAuth token management (Phase 3)
- Protected admin pages/middleware (Phase 2.5 or Phase 3)

### Success Criteria

1. Unauthenticated user visiting admin UI sees login page with Google button
2. Clicking "Sign in with Google" redirects to Google OAuth consent screen
3. After Google approval, callback validates domain and allowlist, creates session
4. Session cookie persists across requests (configurable expiration)
5. Logout endpoint clears session and redirects to login
6. INITIAL_ADMIN_EMAIL user exists in database after first startup
7. Non-@fortiumpartners.com emails are rejected with error message
8. Non-allowlisted @fortiumpartners.com emails are rejected with error message

---

## Acceptance Criteria

### AC1: Google OAuth Configuration

**Given** Google OAuth credentials are configured
**When** settings are loaded
**Then** the application has all necessary OAuth configuration:

| Setting | Purpose | Required |
|---------|---------|----------|
| google_client_id | OAuth application ID from Google Cloud Console | Yes (already in Phase 1) |
| google_client_secret | OAuth application secret | Yes (already in Phase 1) |
| google_allowed_domain | Domain restriction (default: fortiumpartners.com) | Yes (already in Phase 1) |
| initial_admin_email | Email to seed as first admin (with is_super_admin=True) | No (already in Phase 1) |
| app_secret_key | Session signing key | Yes (already in Phase 1) |
| base_url | OAuth redirect URI base (e.g., http://localhost:8000) | Yes (already in Phase 1) |

**OAuth Redirect URI (must be configured in Google Cloud Console):**
```
{base_url}/auth/callback
```

**Example:**
- Local dev: `http://localhost:8000/auth/callback`
- Production: `https://fortium-qbo.example.com/auth/callback`

**Test Scenario:**
```python
from app.config import settings

assert settings.google_client_id
assert settings.google_client_secret
assert settings.google_allowed_domain == "fortiumpartners.com"
assert settings.base_url
assert len(settings.app_secret_key.get_secret_value()) >= 32
```

---

### AC2: Session Management Utility

**Given** the need for secure session management
**When** auth utilities are implemented
**Then** a session management module provides:

**File:** `app/services/session_service.py`

**Functions:**
1. `create_session(email: str) -> str` - Create signed session token
2. `verify_session(token: str) -> str | None` - Verify and extract email from session token
3. Session tokens include:
   - User email
   - Issued-at timestamp
   - Expiration (based on SESSION_MAX_AGE_DAYS)
4. Signed with `app_secret_key` using itsdangerous.URLSafeTimedSerializer

**Test Scenario:**
```python
from app.services.session_service import create_session, verify_session

# Create session
token = create_session("burke@fortiumpartners.com")
assert token
assert len(token) > 20

# Verify session
email = verify_session(token)
assert email == "burke@fortiumpartners.com"

# Invalid token
bad_email = verify_session("invalid-token")
assert bad_email is None

# Expired token (after SESSION_MAX_AGE_DAYS)
# Would return None (tested in unit tests with mocked time)
```

---

### AC3: OAuth Service with Authlib

**Given** Google OAuth credentials
**When** OAuth service is implemented
**Then** it provides OAuth client initialization:

**File:** `app/services/oauth_service.py`

**Functions:**
1. `get_oauth_client() -> OAuth` - Initialize Authlib OAuth client with Google configuration
2. OAuth client configured with:
   - Client ID and secret from settings
   - Authorization endpoint: `https://accounts.google.com/o/oauth2/auth`
   - Token endpoint: `https://oauth2.googleapis.com/token`
   - Scopes: `openid email profile`
   - Redirect URI: `{base_url}/auth/callback`

**Dependencies:**
```python
from authlib.integrations.starlette_client import OAuth
```

**Test Scenario:**
```python
from app.services.oauth_service import get_oauth_client

oauth = get_oauth_client()
assert oauth
assert oauth.google  # Google provider registered
```

---

### AC4: Initial Admin Seeding

**Given** INITIAL_ADMIN_EMAIL is configured
**When** the application starts
**Then** the initial admin user is created if not exists:

**File:** `app/main.py` (lifespan context manager)

**Startup Logic:**
1. If `settings.initial_admin_email` is set:
   - Check if user already exists in admin_users table
   - If not exists, create AdminUser with:
     - email = settings.initial_admin_email
     - is_super_admin = True
     - created_at = now
     - last_login_at = None
   - Log creation: `INFO: Created initial admin user: {email}`
2. If user already exists:
   - Log: `INFO: Initial admin user already exists: {email}`
3. If INITIAL_ADMIN_EMAIL not set:
   - Log: `INFO: No INITIAL_ADMIN_EMAIL configured, skipping admin seeding`

**Error Handling:**
- Database errors during seeding should be logged but not prevent application startup
- Log errors as `ERROR: Failed to seed initial admin user: {error}`

**Test Scenario:**
```bash
# Set INITIAL_ADMIN_EMAIL in .env
echo "INITIAL_ADMIN_EMAIL=burke@fortiumpartners.com" >> .env

# Start application
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Check logs
# Output: INFO: Created initial admin user: burke@fortiumpartners.com

# Restart application
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Check logs
# Output: INFO: Initial admin user already exists: burke@fortiumpartners.com
```

**Database Verification:**
```bash
sqlite3 data/fortium-qbo.db "SELECT email, is_super_admin FROM admin_users WHERE email='burke@fortiumpartners.com';"
# Output: burke@fortiumpartners.com|1
```

---

### AC5: Authentication Router - Login Endpoint

**Given** the OAuth service is configured
**When** `/auth/login` endpoint is implemented
**Then** it initiates Google OAuth flow:

**File:** `app/routers/auth.py`

**Endpoint:** `GET /auth/login`

**Behavior:**
1. Initialize OAuth client
2. Generate authorization URL with Google
3. Redirect user to Google OAuth consent screen
4. Include state parameter for CSRF protection (Authlib handles this automatically)
5. Request scopes: `openid email profile`

**Response:**
- HTTP 302 Redirect to Google OAuth URL

**CSRF Protection:**
- Authlib automatically generates and validates state parameter
- State is stored in session and verified in callback
- No manual state management required

**Test Scenario:**
```bash
# Access login endpoint
curl -i http://localhost:8000/auth/login

# Expected response:
# HTTP/1.1 302 Found
# Location: https://accounts.google.com/o/oauth2/auth?client_id=...&redirect_uri=...&scope=openid+email+profile&state=...

# Verify redirect URL contains:
# - client_id parameter
# - redirect_uri={base_url}/auth/callback
# - scope=openid+email+profile
# - state parameter (CSRF token)
```

---

### AC6: Authentication Router - Callback Endpoint

**Given** user approved OAuth consent on Google
**When** `/auth/callback` endpoint is called with authorization code
**Then** it validates user and creates session:

**File:** `app/routers/auth.py`

**Endpoint:** `GET /auth/callback?code={code}&state={state}`

**Validation Flow:**
1. **OAuth Token Exchange:**
   - Exchange authorization code for access token using Authlib
   - Authlib automatically validates state parameter for CSRF protection
   - Decode ID token to get user info (email, name)
2. **Domain Validation:**
   - Extract email domain
   - Verify domain matches `settings.google_allowed_domain`
   - If mismatch: Return error "Only @fortiumpartners.com emails allowed"
3. **Allowlist Validation:**
   - Query admin_users table for user email
   - If not found: Return error "User not authorized. Contact administrator."
4. **Session Creation:**
   - Create signed session token with user email
   - Set cookie: `session={token}; HttpOnly; Secure; Max-Age={session_max_age_seconds}; Path=/; SameSite=Lax`
5. **Update Last Login:**
   - Update admin_users.last_login_at to current timestamp
6. **Redirect:**
   - Redirect to `/` (root/home page - login page will handle redirect to /admin in future)

**Cookie Configuration:**
- `HttpOnly`: Prevents JavaScript access (XSS protection)
- `Secure`: HTTPS only in production (controlled by settings or environment detection)
- `SameSite=Lax`: CSRF protection while allowing normal navigation
- `Max-Age`: Session expiration in seconds from settings
- `Path=/`: Cookie valid for entire application

**Response on Success:**
- HTTP 302 Redirect to `/`
- Set-Cookie header with session token

**Response on Domain Mismatch:**
- HTTP 400 Bad Request
- HTML error page: "Authentication failed. Only @fortiumpartners.com emails are allowed."

**Response on Allowlist Failure:**
- HTTP 403 Forbidden
- HTML error page: "User not authorized. Please contact your administrator for access."

**Response on OAuth Error:**
- HTTP 400 Bad Request
- HTML error page: "Authentication failed. Please try again or contact your administrator."
- Log error details for debugging

**Test Scenario (Success):**
```bash
# Simulate OAuth callback (in practice, Google redirects here)
curl -i -L http://localhost:8000/auth/callback?code=mock_auth_code&state=mock_state

# Expected:
# HTTP/1.1 302 Found
# Set-Cookie: session=...; HttpOnly; Secure; Max-Age=2592000; Path=/; SameSite=Lax
# Location: /
```

**Test Scenario (Domain Validation):**
```python
# Mock Google OAuth to return personal Gmail
# Expected: HTTP 400 with error message
```

**Test Scenario (Allowlist Validation):**
```python
# Mock Google OAuth to return @fortiumpartners.com email NOT in admin_users
# Expected: HTTP 403 with error message
```

**Database Update Verification:**
```bash
sqlite3 data/fortium-qbo.db "SELECT email, last_login_at FROM admin_users WHERE email='burke@fortiumpartners.com';"
# Output: burke@fortiumpartners.com|2025-12-17 10:30:00.000000
```

---

### AC7: Authentication Router - Logout Endpoint

**Given** an authenticated user session
**When** `/auth/logout` endpoint is called
**Then** it clears the session and redirects to login:

**File:** `app/routers/auth.py`

**Endpoint:** `GET /auth/logout`

**Behavior:**
1. Clear session cookie by setting Max-Age=0
2. Redirect to `/login` (login page)

**Response:**
- HTTP 302 Redirect to `/login`
- Set-Cookie: `session=; Max-Age=0; Path=/`

**Test Scenario:**
```bash
# With active session cookie
curl -i -b "session=valid_token" http://localhost:8000/auth/logout

# Expected response:
# HTTP/1.1 302 Found
# Set-Cookie: session=; Max-Age=0; Path=/
# Location: /login

# Verify session cleared (subsequent requests not authenticated)
curl -i -b "session=valid_token" http://localhost:8000/admin
# Should redirect to login or show unauthorized
```

---

### AC8: Login Page Template

**Given** the need for a user-facing login interface
**When** the login page is created
**Then** it provides a simple Google Sign-In UI:

**File:** `app/templates/login.html`

**Template Directory:**
- Templates must be in `app/templates/` directory (not root-level `templates/`)
- This follows FastAPI/Jinja2 conventions for application-specific templates

**Requirements:**
1. **HTML Structure:**
   - Clean, minimal design
   - Fortium Partners branding (logo/name)
   - "Sign in with Google" button
   - Button links to `/auth/login`
2. **Styling:**
   - Bootstrap 5 for responsive layout
   - Google Sign-In button styling (official Google button design)
   - Centered card layout
3. **Content:**
   - Title: "fortium-qbo Admin"
   - Subtitle: "Sign in with your Fortium Partners Google account"
   - Button text: "Sign in with Google"
   - Footer: "Only @fortiumpartners.com accounts are authorized"

**Login Page Router:**

**File:** `app/routers/pages.py`

**Endpoint:** `GET /login`
- Render `login.html` template
- No authentication required (public endpoint)
- Template directory configured as `Jinja2Templates(directory="app/templates")`

**Test Scenario:**
```bash
# Access login page
curl http://localhost:8000/login

# Verify HTML response contains:
# - "Sign in with Google" button
# - Link to /auth/login (OAuth initiation)
# - Bootstrap CSS
# - fortium-qbo branding
```

**Visual Test:**
```
Visit http://localhost:8000/login in browser
✓ Page loads with centered login card
✓ Google button is visible and styled correctly
✓ Clicking button redirects to Google OAuth
```

---

### AC9: Authenticated Home Page (Root Route)

**Given** user successfully authenticates via OAuth
**When** user is redirected to `/` (root)
**Then** they see a simple authenticated landing page:

**File:** `app/routers/pages.py`

**Endpoint:** `GET /`

**Behavior:**
1. Check for valid session cookie
2. If authenticated: Render home template with user info
3. If not authenticated: Redirect to `/login`

**Template:** `app/templates/home.html`

```html
{% extends "base.html" %}
{% block title %}Home - fortium-qbo{% endblock %}
{% block content %}
<div class="container mt-5">
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card">
                <div class="card-body text-center">
                    <h4 class="card-title">Welcome to fortium-qbo</h4>
                    <p class="card-text">You are authenticated as:</p>
                    <p class="fw-bold">{{ user.email }}</p>
                    <hr>
                    <p class="text-muted small">Admin features coming in Phase 3+</p>
                    <a href="/auth/logout" class="btn btn-outline-secondary">Logout</a>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

**Response (Authenticated):**
- HTTP 200 OK
- HTML page showing user email and logout button

**Response (Not Authenticated):**
- HTTP 302 Redirect to `/login`

**Test Scenario:**
```bash
# With valid session cookie
curl -i -b "session=valid_token" http://localhost:8000/

# Expected:
# HTTP/1.1 200 OK
# Content contains "Welcome to fortium-qbo"
# Content contains user email
# Content contains logout link

# Without session cookie
curl -i http://localhost:8000/

# Expected:
# HTTP/1.1 302 Found
# Location: /login
```

**Visual Test:**
```
1. Complete OAuth login flow
2. After callback, browser should land on /
3. Page shows "Welcome to fortium-qbo"
4. User email is displayed
5. Logout button is visible and functional
```

---

### AC10: Authentication Dependencies (Prep for Future Phases)

**Given** authenticated routes will be needed in future phases
**When** authentication dependencies are implemented
**Then** they provide reusable authentication checking:

**File:** `app/dependencies.py`

**Function:** `get_current_admin_user(request: Request) -> AdminUser | None`

**Behavior:**
1. Extract session cookie from request
2. Verify session token using session_service
3. If valid:
   - Extract email from token
   - Query admin_users table for user
   - Return AdminUser object
4. If invalid or missing:
   - Return None (or raise HTTPException based on usage)

**Usage (Future Phases):**
```python
from fastapi import Depends
from app.dependencies import get_current_admin_user
from app.models import AdminUser

@app.get("/admin/dashboard")
async def admin_dashboard(
    current_user: AdminUser = Depends(get_current_admin_user)
):
    if not current_user:
        raise HTTPException(401, "Not authenticated")
    return {"user": current_user.email}
```

**Test Scenario:**
```python
from app.dependencies import get_current_admin_user
from app.services.session_service import create_session
from fastapi import Request

# Create mock request with valid session
token = create_session("burke@fortiumpartners.com")
request = Request(scope={"type": "http", "headers": [(b"cookie", f"session={token}".encode())]})

# Get current user
user = await get_current_admin_user(request)
assert user
assert user.email == "burke@fortiumpartners.com"

# Test invalid session
request_invalid = Request(scope={"type": "http", "headers": [(b"cookie", b"session=invalid")]})
user_invalid = await get_current_admin_user(request_invalid)
assert user_invalid is None
```

---

### AC11: Router Registration

**Given** all authentication endpoints are implemented
**When** routers are registered in main.py
**Then** all auth routes are accessible:

**File:** `app/main.py`

**Changes:**
```python
from app.routers import auth, pages

# Include routers
app.include_router(auth.router)
app.include_router(pages.router)
```

**Registered Routes:**
- `GET /` - Authenticated home page (via pages router)
- `GET /auth/login` - Initiate OAuth flow
- `GET /auth/callback` - OAuth callback handler
- `GET /auth/logout` - Logout and clear session
- `GET /login` - Render login page (via pages router)

**Test Scenario:**
```bash
# Verify all routes registered
curl http://localhost:8000/openapi.json | jq '.paths | keys'

# Expected output includes:
# "/"
# "/auth/login"
# "/auth/callback"
# "/auth/logout"
# "/login"
```

---

### AC12: Dependencies Update

**Given** new dependencies are required for OAuth
**When** requirements.txt is updated
**Then** it includes OAuth libraries:

**File:** `requirements.txt`

**Verification (already in Phase 1):**
```
# OAuth 2.0 (Google authentication)
authlib>=1.3.0
itsdangerous>=2.1.0    # Already in Phase 1
httpx>=0.26.0          # Already in Phase 1, Authlib async HTTP client
```

**Test Scenario:**
```bash
cd /Users/burke/projects/fpqbo/fortium-qbo
source venv/bin/activate
pip install -r requirements.txt

# Verify imports
python -c "from authlib.integrations.starlette_client import OAuth; print('OK')"
# Output: OK

python -c "from itsdangerous import URLSafeTimedSerializer; print('OK')"
# Output: OK
```

---

### AC13: Environment Configuration

**Given** OAuth credentials from Google Cloud Console
**When** .env.example is updated
**Then** it includes OAuth setup instructions:

**File:** `.env.example`

**Updates (OAuth section):**
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

---

### AC14: Documentation Updates

**Given** Phase 2 implementation
**When** README.md is updated
**Then** it includes authentication setup instructions:

**File:** `README.md`

**New Section:**
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

---

## Technical Notes

### Pattern Reference: pipelinemgr + linkedin-workspace

The implementation should follow established patterns:

**Session Management Pattern (itsdangerous):**
- Use `itsdangerous.URLSafeTimedSerializer` for signed cookies
- Session token includes email + timestamp
- Verify tokens on each request via dependency
- No database storage of session tokens (stateless sessions)

**OAuth Pattern (Authlib):**
- Use `authlib.integrations.starlette_client.OAuth` for Google OAuth
- Follow standard OAuth 2.0 Authorization Code flow
- Store minimal session data (email only, lookup rest from DB)
- Authlib handles state parameter for CSRF protection automatically

**Service Layer Pattern:**
- `app/services/session_service.py` - Session token creation/verification
- `app/services/oauth_service.py` - OAuth client initialization
- Pure functions for testability

**Router Pattern:**
- `app/routers/auth.py` - All auth endpoints (/auth/login, /auth/callback, /auth/logout)
- `app/routers/pages.py` - HTML page rendering (login page)
- Thin controllers, business logic in services

**Template Pattern:**
- Templates in `app/templates/` directory (not root-level)
- Jinja2Templates configured with `directory="app/templates"`
- Follow pipelinemgr Bootstrap 5 pattern

### File References

| Component | Reference Pattern |
|-----------|------------------|
| Session management | `itsdangerous` library (new pattern for this project) |
| OAuth client | `authlib` library documentation |
| Config pattern | `pipelinemgr/app/config.py` (already implemented) |
| Template rendering | `pipelinemgr/app/routers/pages.py` + `pipelinemgr/templates/base.html` |

### OAuth Flow Diagram

```
User → /login (pages.router)
  ↓ Click "Sign in with Google"
  ↓
/auth/login (auth.router)
  ↓ Redirect to Google (with state for CSRF)
  ↓
Google OAuth Consent Screen
  ↓ User approves
  ↓
/auth/callback?code=xxx&state=yyy (auth.router)
  ↓ Authlib validates state (CSRF protection)
  ↓ Exchange code for token
  ↓ Validate domain (fortiumpartners.com)
  ↓ Check admin_users allowlist
  ↓ Create session cookie
  ↓ Update last_login_at
  ↓ Redirect to /
  ↓
Root/Home Page (login page handles redirect logic)
```

### Security Considerations

1. **Session Security:**
   - Signed cookies prevent tampering (itsdangerous)
   - HttpOnly flag prevents XSS access to cookies
   - Secure flag enforces HTTPS (production)
   - SameSite=Lax prevents CSRF
   - Configurable expiration (default 30 days)
   - Stateless sessions (no server-side storage needed)

2. **OAuth Security:**
   - State parameter prevents CSRF on OAuth flow (Authlib automatic)
   - Tokens stored server-side only (not in cookies)
   - Domain validation prevents unauthorized email domains
   - Allowlist validation provides defense in depth
   - OAuth tokens discarded after session creation (no long-term storage)

3. **Database Security:**
   - Admin emails are unique and indexed
   - Email validation happens at multiple layers
   - Last login tracking for audit trail
   - Super admin flag for future privilege escalation

4. **Error Handling:**
   - OAuth errors logged with details for debugging
   - User-facing errors are generic to prevent information leakage
   - Failed auth attempts tracked via request logs (future enhancement)

### Testing Strategy

**Unit Tests:**
- `tests/test_session_service.py` - Session token creation/verification
- `tests/test_oauth_service.py` - OAuth client initialization
- `tests/test_auth_router.py` - Auth endpoints with mocked OAuth

**Integration Tests:**
- End-to-end OAuth flow with mock Google OAuth server
- Session persistence across requests
- Domain validation edge cases
- Allowlist validation edge cases
- Cookie security attributes (HttpOnly, Secure, SameSite)

**Manual Tests:**
- Real Google OAuth flow (local development)
- Cookie inspection in browser DevTools
- Login/logout round trip
- Session expiration after MAX_AGE
- Error pages for domain/allowlist failures

---

## Appendix

### Related Documents

- [Phase 1 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
- [Linear Issue FOR-82](https://linear.app/fortiumpartners/issue/FOR-82/phase-2-admin-authentication)

### Phase Dependencies

```
Phase 1 (Core) ──► Phase 2 (This PRD - Admin Auth)
                         ↓
                   Phase 2.5 (Protected Routes)
                         ↓
                   Phase 3 (QBO Tokens)
```

Phase 2 depends on Phase 1 (models, config, FastAPI app).
Phase 3 (QBO token management) depends on Phase 2 (admin authentication).

### Checklist for Phase 2 Completion

- [ ] Session service with create/verify functions
- [ ] OAuth service with Authlib integration
- [ ] Initial admin seeding in lifespan startup
- [ ] Auth router with /login, /callback, /logout endpoints
- [ ] Pages router with login page template
- [ ] Login page HTML with Google button (in app/templates/)
- [ ] Domain validation (@fortiumpartners.com)
- [ ] Allowlist validation (admin_users table)
- [ ] Session cookie configuration (HttpOnly, Secure, SameSite)
- [ ] Last login timestamp update on callback
- [ ] Authentication dependency for future use
- [ ] requirements.txt updated with authlib (verified from Phase 1)
- [ ] .env.example updated with OAuth instructions
- [ ] README.md updated with setup instructions
- [ ] Error handling for OAuth failures
- [ ] CSRF protection via Authlib state parameter
- [ ] Error pages for domain/allowlist failures
- [ ] Manual test: Complete OAuth flow succeeds for allowlisted user
- [ ] Manual test: Non-domain email rejected
- [ ] Manual test: Non-allowlisted email rejected
- [ ] Manual test: Session persists across requests
- [ ] Manual test: Logout clears session

### Environment Variables Summary

Phase 2 uses these environment variables (all already defined in Phase 1 config):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| GOOGLE_CLIENT_ID | Yes | - | OAuth client ID from Google Cloud Console |
| GOOGLE_CLIENT_SECRET | Yes | - | OAuth client secret |
| GOOGLE_ALLOWED_DOMAIN | No | fortiumpartners.com | Email domain restriction |
| INITIAL_ADMIN_EMAIL | No | None | First admin user to seed on startup |
| APP_SECRET_KEY | Yes | - | Session cookie signing key (min 32 chars) |
| SESSION_MAX_AGE_DAYS | No | 30 | Session cookie expiration |
| BASE_URL | Yes | http://localhost:8000 | OAuth redirect URI base |

### Google Cloud Console Setup

**Quick Setup Guide:**

1. Navigate to https://console.cloud.google.com/
2. Create new project: "fortium-qbo"
3. Enable APIs: "Google+ API" or "Google People API"
4. Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: Web application
6. Name: "fortium-qbo-admin"
7. Authorized JavaScript origins:
   - `http://localhost:8000` (development)
   - `https://your-production-domain.com` (production)
8. Authorized redirect URIs:
   - `http://localhost:8000/auth/callback` (development)
   - `https://your-production-domain.com/auth/callback` (production)
9. Create → Copy Client ID and Client Secret to .env
10. OAuth consent screen → Configure (Internal for Google Workspace, or External with test users)

### Future Enhancements (Post-Phase 2)

1. **Admin Management UI:**
   - Add/remove admin users via web interface
   - Toggle super_admin status
   - View admin user list with last login times

2. **Role-Based Access Control:**
   - Define permissions beyond super_admin flag
   - Route-level authorization decorators
   - Audit log for admin actions

3. **Session Improvements:**
   - "Remember me" checkbox (extended session)
   - Concurrent session limits
   - Session invalidation (force logout all sessions)

4. **OAuth Enhancements:**
   - Support multiple OAuth providers (Microsoft, Okta)
   - Refresh token storage for offline access
   - Profile picture from Google account

These are explicitly out of scope for Phase 2 but documented for future reference.
