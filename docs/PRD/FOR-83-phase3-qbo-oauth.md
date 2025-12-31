# PRD: Phase 3 - QBO OAuth Token Management

**Issue:** [FOR-83](https://linear.app/fortiumpartners/issue/FOR-83/phase-3-qbo-oauth-token-management)
**Project:** fortium-qbo
**Date:** 2025-12-31
**Status:** Ready for TRD
**Version:** 1.0

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-31 | Initial PRD creation |

---

## Product Summary

### Problem Statement

The fortium-qbo API gateway currently relies on manually-configured environment variables for QBO OAuth tokens:
- Tokens stored in `.env` file require manual rotation
- No admin visibility into token status or expiration
- Manual OAuth flow through Intuit Developer Portal to obtain tokens
- No multi-company support - single company hardcoded
- Token refresh happens at runtime but new companies cannot be added without developer intervention

This creates operational burden and prevents non-technical administrators from managing QBO connections.

### Solution

Implement a complete QBO OAuth connection flow with admin UI and database-driven token management:
1. **OAuth Connect Flow** - Admin-initiated OAuth to connect QBO companies
2. **Database Token Storage** - Store tokens in existing `qbo_companies` table
3. **Automatic Token Refresh** - Existing QBOService refresh logic integrated with database
4. **Admin UI for Company Management** - View, connect, disconnect QBO companies
5. **Token Status Monitoring** - Visual indicators for token health and expiration

### Value Proposition

This phase establishes:
- **Self-Service** - Admins can connect/disconnect QBO companies without developer help
- **Reliability** - Automatic token refresh with database persistence
- **Visibility** - Dashboard showing token status, last refresh, expiration
- **Multi-Company** - Foundation for managing multiple QBO companies
- **Security** - Tokens stored in database, not environment files

---

## User Analysis

### Primary Users

| User Type | Description | Needs |
|-----------|-------------|-------|
| **Admin Users** | Fortium Partners staff managing QBO connections | Connect QBO companies, view token status, troubleshoot connection issues |
| **Developer (Burke)** | Implements and maintains system | Clear OAuth patterns, reliable token management, minimal manual intervention |
| **Automated Systems** | n8n workflows, scheduled jobs | Reliable API access with auto-refreshed tokens |

### User Personas

#### Burke (Admin & Developer)
- **Role:** Primary administrator and developer
- **Context:** Needs to connect Fortium Partners QBO and potentially additional companies
- **Pain Points:** Currently must manually refresh tokens, update .env, restart services
- **Goals:** One-click QBO connection, automatic token refresh, clear status visibility

#### Future Finance Staff (Admin User)
- **Role:** Non-technical admin who manages QBO data
- **Context:** May need to reconnect QBO if authorization is revoked
- **Pain Points:** Cannot self-service token issues, must request developer help
- **Goals:** Simple "Connect to QuickBooks" button, clear error messages if issues

### User Journey: Connecting QBO Company

```
1. Admin logs in via Google OAuth (Phase 2)
2. Admin navigates to /admin/companies
3. Admin clicks "Connect QuickBooks"
4. Admin is redirected to Intuit OAuth consent screen
5. Admin approves access to QBO company data
6. System receives authorization code, exchanges for tokens
7. System stores tokens in qbo_companies table
8. Admin sees success message, company appears in list
9. Admin can now access QBO data via API endpoints
```

### Pain Points Addressed

1. **Manual token management** -> Automatic OAuth flow and token refresh
2. **No visibility into token status** -> Admin dashboard with expiration countdown
3. **Developer-only QBO setup** -> Self-service admin UI for connections
4. **Single company limitation** -> Database-driven multi-company support

---

## Goals & Non-Goals

### Goals

| Goal | Success Metric |
|------|----------------|
| Admin can initiate QBO OAuth connection | `/admin/companies/connect` redirects to Intuit OAuth |
| System stores tokens in database | Tokens persisted to `qbo_companies` table on callback |
| Automatic token refresh works | Tokens refreshed before expiration, no manual intervention |
| Admin can view connected companies | `/admin/companies` shows list with status indicators |
| Admin can disconnect companies | "Disconnect" action clears tokens, marks status inactive |
| Token status is visible | Show "Active/Expiring Soon/Expired" with time remaining |

### Non-Goals (Out of Scope for Phase 3)

- API key management UI (Phase 4)
- Multiple user roles/permissions for QBO access
- QBO company selection during OAuth (connect all accessible companies)
- Webhook notifications for token expiration
- Token encryption at rest (use application-level secrets management)
- QBO sandbox/development environment support (production only)
- Bulk company import

### Success Criteria

1. Admin can connect a QBO company through OAuth flow in under 30 seconds
2. Tokens persist across application restarts (database storage)
3. Token refresh happens automatically before expiration (5-minute buffer)
4. Admin dashboard shows accurate token status and expiration time
5. Disconnecting a company immediately invalidates API access
6. OAuth errors display clear, actionable error messages

---

## Functional Requirements

### FR1: QBO OAuth Configuration

**Description:** Configure QBO OAuth credentials and endpoints.

**Requirements:**
1. Add QBO OAuth settings to config (already partially exists):
   - `QBO_CLIENT_ID` - Intuit OAuth app client ID
   - `QBO_CLIENT_SECRET` - Intuit OAuth app client secret
   - `QBO_REDIRECT_URI` - OAuth callback URL (default: `{base_url}/api/qbo/callback`)
2. OAuth scopes required: `com.intuit.quickbooks.accounting`
3. Environment: Production (not sandbox)

**Config Update:**
```python
# QBO OAuth (Required for Phase 3+)
qbo_client_id: str = Field(min_length=1)
qbo_client_secret: SecretStr = Field(min_length=1)
qbo_redirect_uri: str | None = None  # Defaults to {base_url}/api/qbo/callback
```

---

### FR2: OAuth Connect Endpoint

**Description:** Initiate QBO OAuth flow for connecting a company.

**Endpoint:** `GET /api/qbo/connect`

**Requirements:**
1. Require authenticated admin session (Phase 2 dependency)
2. Generate OAuth authorization URL using intuit-oauth library
3. Include state parameter for CSRF protection
4. Store state in session for callback validation
5. Redirect to Intuit OAuth consent screen

**Request:**
```
GET /api/qbo/connect
Cookie: session=<admin_session_token>
```

**Response:**
```
HTTP/1.1 302 Found
Location: https://appcenter.intuit.com/connect/oauth2?
  client_id=<qbo_client_id>&
  response_type=code&
  scope=com.intuit.quickbooks.accounting&
  redirect_uri=<redirect_uri>&
  state=<csrf_state>
```

---

### FR3: OAuth Callback Endpoint

**Description:** Handle OAuth callback and store tokens.

**Endpoint:** `GET /api/qbo/callback`

**Requirements:**
1. Validate state parameter matches session (CSRF protection)
2. Exchange authorization code for access and refresh tokens
3. Extract realm_id (company ID) from callback
4. Query QBO Company Info API to get company name
5. Create or update `qbo_companies` record:
   - If realm_id exists: Update tokens and status
   - If new: Create company record with auto-generated code
6. Set token_status = "active"
7. Calculate and store token_expires_at (1 hour from now)
8. Redirect to admin companies page with success message

**Callback URL:**
```
GET /api/qbo/callback?code=<auth_code>&state=<csrf_state>&realmId=<qbo_company_id>
```

**Success Response:**
```
HTTP/1.1 302 Found
Location: /admin/companies?message=connected
Set-Cookie: flash_message=Successfully connected QuickBooks company
```

**Error Response (Invalid State):**
```
HTTP/1.1 400 Bad Request
Content-Type: text/html

OAuth authentication failed: Invalid state parameter. Please try again.
```

**Error Response (Token Exchange Failed):**
```
HTTP/1.1 400 Bad Request
Content-Type: text/html

Failed to connect QuickBooks: Unable to exchange authorization code. Please try again.
```

---

### FR4: Company Info Retrieval

**Description:** Fetch QBO company details after OAuth.

**Requirements:**
1. After token exchange, call QBO Company Info API
2. Extract company name for display
3. Store company name in `qbo_companies.name`
4. Handle API errors gracefully (default to "Unknown Company")

**QBO API Call:**
```
GET https://quickbooks.api.intuit.com/v3/company/<realmId>/companyinfo/<realmId>
Authorization: Bearer <access_token>
Accept: application/json
```

---

### FR5: Token Refresh Integration

**Description:** Integrate existing QBOService token refresh with database.

**Requirements:**
1. QBOService `_refresh_token` already updates database (verified in existing code)
2. Ensure refresh works for OAuth-connected companies
3. Update `token_status` to "active" after successful refresh
4. Update `last_refreshed_at` timestamp
5. Handle refresh failures by setting `token_status` to "expired"

**Existing Logic (QBOService._refresh_token):**
```python
# Update company record
company.access_token = auth_client.access_token
company.refresh_token = auth_client.refresh_token
company.token_expires_at = datetime.utcnow() + timedelta(hours=1)
company.last_refreshed_at = datetime.utcnow()
company.token_status = "active"
self.db.commit()
```

---

### FR6: Admin Companies Page

**Description:** Admin UI to view and manage connected QBO companies.

**Endpoint:** `GET /admin/companies`

**Requirements:**
1. Require authenticated admin session
2. Display table of QBO companies with:
   - Company name
   - Company code
   - Realm ID
   - Token status (Active/Expiring Soon/Expired/Not Connected)
   - Token expires in (human-readable countdown)
   - Last refreshed timestamp
   - Actions (Disconnect, Refresh)
3. "Connect QuickBooks" button to initiate OAuth
4. Flash message display for success/error notifications

**Token Status Logic:**
- `Active`: token_expires_at > now + 30 minutes
- `Expiring Soon`: token_expires_at > now but < now + 30 minutes (yellow warning)
- `Expired`: token_expires_at <= now (red indicator)
- `Not Connected`: access_token is null

**Template:** `app/templates/admin/companies.html`

---

### FR7: Disconnect Company

**Description:** Revoke OAuth connection and clear tokens.

**Endpoint:** `POST /api/qbo/companies/{company_id}/disconnect`

**Requirements:**
1. Require authenticated admin session
2. Clear tokens from database:
   - Set access_token = NULL
   - Set refresh_token = NULL
   - Set token_expires_at = NULL
   - Set token_status = "disconnected"
3. Optionally revoke token with Intuit (best effort, don't fail on error)
4. Redirect to companies page with success message

**Request:**
```
POST /api/qbo/companies/1/disconnect
Cookie: session=<admin_session_token>
```

**Response:**
```
HTTP/1.1 302 Found
Location: /admin/companies?message=disconnected
```

---

### FR8: Manual Token Refresh

**Description:** Allow admin to manually trigger token refresh.

**Endpoint:** `POST /api/qbo/companies/{company_id}/refresh`

**Requirements:**
1. Require authenticated admin session
2. Call QBOService token refresh logic
3. Update token status and timestamps
4. Return success/failure indication
5. Handle expired refresh tokens (require reconnect)

**Request:**
```
POST /api/qbo/companies/1/refresh
Cookie: session=<admin_session_token>
```

**Success Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "expires_at": "2025-12-31T13:00:00Z"
}
```

**Failure Response:**
```json
{
  "success": false,
  "message": "Refresh token expired. Please reconnect QuickBooks.",
  "reconnect_required": true
}
```

---

### FR9: QBO Service OAuth Integration

**Description:** Modify QBOService to work with database-stored tokens.

**Requirements:**
1. QBOService already uses database tokens (verified)
2. Add company lookup by code (convenience method)
3. Handle "disconnected" token status
4. Throw clear error when token refresh fails

**New Method:**
```python
def get_company_by_code(self, code: str) -> QboCompany:
    """Get QBO company by code."""
    company = self.db.query(QboCompany).filter(QboCompany.code == code).first()
    if not company:
        raise ValueError(f"QBO company not found: {code}")
    if company.token_status == "disconnected":
        raise ValueError(f"QBO company {code} is disconnected. Please reconnect.")
    return company
```

---

### FR10: Company Code Generation

**Description:** Auto-generate unique company codes for new connections.

**Requirements:**
1. When creating new company from OAuth, generate code
2. Format: First 3 chars of company name (uppercase) + "-" + 3 random digits
3. Ensure uniqueness (check for collisions)
4. Allow admin to edit code after creation (future enhancement)

**Examples:**
- "Fortium Partners" -> "FOR-482"
- "Test Company" -> "TES-127"
- "A B C Corp" -> "ABC-951"

---

## Non-Functional Requirements

### NFR1: Security

| Requirement | Implementation |
|-------------|----------------|
| CSRF Protection | State parameter validated in OAuth callback |
| Token Storage | Tokens stored in database, not logs or responses |
| Admin Authentication | All company management endpoints require valid admin session |
| Token Exposure | Access tokens never exposed in URL parameters or client-side code |
| Secure Transmission | HTTPS required for production OAuth callbacks |

### NFR2: Performance

| Requirement | Target |
|-------------|--------|
| OAuth Flow Completion | < 5 seconds (excluding user interaction with Intuit) |
| Token Refresh | < 2 seconds |
| Companies Page Load | < 500ms |
| Database Queries | Use indexed lookups (realm_id, code) |

### NFR3: Reliability

| Requirement | Implementation |
|-------------|----------------|
| Token Refresh Buffer | Refresh tokens 5 minutes before expiration |
| Retry Logic | Retry token refresh once on transient failures |
| Graceful Degradation | Clear error messages when QBO unavailable |
| Data Integrity | Transaction rollback on partial OAuth failures |

### NFR4: Observability

| Requirement | Implementation |
|-------------|----------------|
| OAuth Event Logging | Log connect, callback, disconnect, refresh events |
| Token Status Tracking | Log token status changes |
| Error Logging | Log OAuth errors with correlation IDs |
| Metrics | Track token refresh success/failure rates |

---

## Acceptance Criteria

### AC1: QBO OAuth Configuration

**Given** QBO OAuth credentials from Intuit Developer Portal
**When** environment is configured
**Then** application has all necessary OAuth settings:

| Setting | Purpose | Required |
|---------|---------|----------|
| QBO_CLIENT_ID | Intuit OAuth app client ID | Yes |
| QBO_CLIENT_SECRET | Intuit OAuth app client secret | Yes |
| QBO_REDIRECT_URI | OAuth callback URL (defaults to {base_url}/api/qbo/callback) | No |

**Test Scenario:**
```python
from app.config import settings

assert settings.qbo_client_id
assert settings.qbo_client_secret
# Redirect URI defaults if not set
redirect_uri = settings.qbo_redirect_uri or f"{settings.base_url}/api/qbo/callback"
assert "callback" in redirect_uri
```

---

### AC2: OAuth Connect Flow

**Given** authenticated admin user on companies page
**When** admin clicks "Connect QuickBooks"
**Then** admin is redirected to Intuit OAuth consent screen:

1. Redirect URL contains correct client_id
2. Redirect URL requests `com.intuit.quickbooks.accounting` scope
3. Redirect URL includes state parameter for CSRF
4. State is stored in session for callback validation

**Test Scenario:**
```bash
# With valid admin session
curl -i -b "session=<admin_token>" http://localhost:8086/api/qbo/connect

# Expected:
# HTTP/1.1 302 Found
# Location: https://appcenter.intuit.com/connect/oauth2?client_id=...&scope=com.intuit.quickbooks.accounting&state=...
```

---

### AC3: OAuth Callback Success

**Given** user approved QBO OAuth consent
**When** Intuit redirects to callback with authorization code
**Then** system exchanges code for tokens and creates company record:

1. State parameter validated against session
2. Authorization code exchanged for access/refresh tokens
3. QBO Company Info API called to get company name
4. New `qbo_companies` record created with:
   - name from Company Info API
   - code auto-generated
   - realm_id from callback
   - access_token and refresh_token stored
   - token_expires_at set to 1 hour from now
   - token_status = "active"
5. Admin redirected to /admin/companies with success message

**Test Scenario (Manual):**
```
1. Navigate to http://localhost:8086/admin/companies
2. Click "Connect QuickBooks"
3. Log in to QBO if prompted
4. Approve access on consent screen
5. Verify redirect to /admin/companies
6. Verify company appears in list with "Active" status
```

**Database Verification:**
```bash
sqlite3 data/fortium-qbo.db "SELECT name, code, realm_id, token_status FROM qbo_companies;"
# Output: Fortium Partners|FOR-XXX|1208415120|active
```

---

### AC4: OAuth Callback Error Handling

**Given** OAuth callback receives error or invalid state
**When** callback endpoint is hit
**Then** appropriate error is displayed:

| Scenario | Expected Behavior |
|----------|-------------------|
| Invalid state parameter | 400 error: "Invalid state parameter. Please try again." |
| Missing authorization code | 400 error: "Authorization code missing. Please try again." |
| Token exchange failure | 400 error: "Unable to exchange authorization code." |
| QBO API error | Company created with "Unknown Company" name, tokens stored |
| Duplicate realm_id | Existing company updated with new tokens |

**Test Scenario:**
```bash
# Invalid state
curl -i "http://localhost:8086/api/qbo/callback?code=test&state=invalid&realmId=123"

# Expected: HTTP/1.1 400 Bad Request
# Body contains "Invalid state parameter"
```

---

### AC5: Admin Companies Page

**Given** authenticated admin user
**When** admin visits /admin/companies
**Then** page displays connected companies with status:

**Page Elements:**
1. "Connect QuickBooks" button (visible)
2. Companies table with columns:
   - Name | Code | Realm ID | Status | Expires In | Last Refresh | Actions
3. Status badges:
   - Green "Active" for healthy tokens
   - Yellow "Expiring Soon" for tokens expiring within 30 min
   - Red "Expired" for expired tokens
   - Gray "Disconnected" for cleared tokens
4. "Disconnect" and "Refresh" action buttons per company

**Test Scenario:**
```bash
# With valid admin session
curl -b "session=<admin_token>" http://localhost:8086/admin/companies

# Expected: HTML page with companies table
# Contains "Connect QuickBooks" button
# Contains company list (if any connected)
```

---

### AC6: Token Status Display

**Given** connected QBO company with known token expiration
**When** admin views companies page
**Then** token status displays correctly:

| Token Expires At | Display |
|------------------|---------|
| > 30 minutes from now | "Active" (green) + "Expires in X hours" |
| 5-30 minutes from now | "Expiring Soon" (yellow) + "Expires in X minutes" |
| < 5 minutes from now | "Expiring Soon" (yellow) + "Expires in X minutes" |
| In the past | "Expired" (red) + "Expired X ago" |
| NULL | "Not Connected" (gray) |

**Test Scenario:**
```python
# Unit test for status logic
from datetime import datetime, timedelta

def get_token_status(expires_at: datetime | None) -> tuple[str, str]:
    if expires_at is None:
        return ("disconnected", "Not Connected")
    now = datetime.utcnow()
    if expires_at <= now:
        return ("expired", "Expired")
    elif expires_at <= now + timedelta(minutes=30):
        return ("expiring_soon", "Expiring Soon")
    else:
        return ("active", "Active")
```

---

### AC7: Disconnect Company

**Given** connected QBO company
**When** admin clicks "Disconnect" and confirms
**Then** company tokens are cleared:

1. access_token set to NULL
2. refresh_token set to NULL
3. token_expires_at set to NULL
4. token_status set to "disconnected"
5. Admin redirected with success message
6. Company still appears in list but with "Disconnected" status
7. API requests to that company fail with clear error

**Test Scenario:**
```bash
# Disconnect company
curl -X POST -b "session=<admin_token>" http://localhost:8086/api/qbo/companies/1/disconnect

# Expected: 302 redirect to /admin/companies

# Verify in database
sqlite3 data/fortium-qbo.db "SELECT token_status, access_token FROM qbo_companies WHERE id=1;"
# Output: disconnected|
```

---

### AC8: Manual Token Refresh

**Given** connected QBO company with valid refresh token
**When** admin clicks "Refresh" button
**Then** token is refreshed:

1. New access token obtained from Intuit
2. token_expires_at updated to 1 hour from now
3. last_refreshed_at updated to current time
4. token_status remains "active"
5. Success message displayed to admin

**Test Scenario:**
```bash
# Manual refresh
curl -X POST -b "session=<admin_token>" http://localhost:8086/api/qbo/companies/1/refresh

# Expected:
# {"success": true, "message": "Token refreshed successfully", "expires_at": "..."}
```

---

### AC9: Automatic Token Refresh

**Given** connected QBO company with token expiring within 5 minutes
**When** QBOService makes API request
**Then** token is automatically refreshed:

1. `_needs_refresh()` returns True
2. `_refresh_token()` called before API request
3. New tokens persisted to database
4. API request succeeds with fresh token

**Test Scenario:**
```python
# Set token to expire in 3 minutes
company.token_expires_at = datetime.utcnow() + timedelta(minutes=3)
db.commit()

# Make API request
service = QBOService(db)
invoices = await service.get_invoices(company.id)

# Verify token was refreshed
db.refresh(company)
assert company.token_expires_at > datetime.utcnow() + timedelta(minutes=50)
```

---

### AC10: Router Registration

**Given** QBO OAuth endpoints are implemented
**When** routers are registered in main.py
**Then** all QBO routes are accessible:

**New Router:** `app/routers/qbo_oauth.py`

**Registered Routes:**
- `GET /api/qbo/connect` - Initiate OAuth flow
- `GET /api/qbo/callback` - OAuth callback handler
- `POST /api/qbo/companies/{id}/disconnect` - Disconnect company
- `POST /api/qbo/companies/{id}/refresh` - Manual token refresh

**Admin Page Routes (via pages router):**
- `GET /admin/companies` - Companies management page

**Test Scenario:**
```bash
curl http://localhost:8086/openapi.json | jq '.paths | keys' | grep qbo

# Expected output includes:
# "/api/qbo/connect"
# "/api/qbo/callback"
# "/api/qbo/companies/{company_id}/disconnect"
# "/api/qbo/companies/{company_id}/refresh"
```

---

### AC11: Authentication Requirement

**Given** QBO management endpoints
**When** unauthenticated user attempts access
**Then** user is redirected to login:

| Endpoint | Unauthenticated Behavior |
|----------|--------------------------|
| GET /api/qbo/connect | Redirect to /login |
| GET /api/qbo/callback | Redirect to /login |
| POST /api/qbo/companies/{id}/disconnect | Redirect to /login |
| POST /api/qbo/companies/{id}/refresh | Redirect to /login |
| GET /admin/companies | Redirect to /login |

**Test Scenario:**
```bash
# Without session cookie
curl -i http://localhost:8086/api/qbo/connect

# Expected:
# HTTP/1.1 302 Found
# Location: /login
```

---

### AC12: Environment Configuration

**Given** QBO OAuth credentials from Intuit Developer Portal
**When** .env is configured
**Then** application can complete OAuth flow:

**File:** `.env.example` (updates)

```bash
# QBO OAuth (Required for Phase 3+)
# 1. Create app at https://developer.intuit.com/app/developer/qbo/docs/get-started
# 2. Configure redirect URI: {BASE_URL}/api/qbo/callback
# 3. Copy Client ID and Client Secret below
QBO_CLIENT_ID=your-qbo-client-id
QBO_CLIENT_SECRET=your-qbo-client-secret

# Optional: Override redirect URI (defaults to {BASE_URL}/api/qbo/callback)
# QBO_REDIRECT_URI=https://your-domain.com/api/qbo/callback
```

---

### AC13: Documentation Updates

**Given** Phase 3 implementation
**When** README.md is updated
**Then** it includes QBO OAuth setup instructions:

**New Section:**
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
   - Redirect URIs:
     - Local: `http://localhost:8086/api/qbo/callback`
     - Production: `https://your-domain.com/api/qbo/callback`
   - Scopes: Select "Accounting"

4. **Get Credentials:**
   - Copy Client ID and Client Secret
   - Add to .env file

### Connecting QuickBooks

1. Start the application
2. Log in at http://localhost:8086/login (Google OAuth)
3. Navigate to /admin/companies
4. Click "Connect QuickBooks"
5. Authorize access on Intuit consent screen
6. Company appears in list with "Active" status

### Token Management

- Tokens automatically refresh before expiration
- Manual refresh available via "Refresh" button
- "Disconnect" removes tokens and requires re-authorization
```

---

## Technical Notes

### OAuth Flow Diagram

```
Admin visits /admin/companies
         |
         v
Click "Connect QuickBooks"
         |
         v
GET /api/qbo/connect
         |
         +-- Generate state (CSRF)
         +-- Store state in session
         |
         v
Redirect to Intuit OAuth
https://appcenter.intuit.com/connect/oauth2?
  client_id=...&scope=...&state=...
         |
         v
User approves on Intuit consent screen
         |
         v
GET /api/qbo/callback?code=...&state=...&realmId=...
         |
         +-- Validate state matches session
         +-- Exchange code for tokens
         +-- Fetch company info from QBO API
         +-- Create/update qbo_companies record
         |
         v
Redirect to /admin/companies?message=connected
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

### Intuit OAuth Endpoints

| Purpose | URL |
|---------|-----|
| Authorization | https://appcenter.intuit.com/connect/oauth2 |
| Token Exchange | https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer |
| Token Revoke | https://developer.api.intuit.com/v2/oauth2/tokens/revoke |
| Company Info | https://quickbooks.api.intuit.com/v3/company/{realmId}/companyinfo/{realmId} |

### Dependencies

Phase 3 uses these existing libraries:
- `intuitlib` - Intuit OAuth client (AuthClient)
- `httpx` - Async HTTP client for Company Info API
- `python-quickbooks` - QBO SDK (already integrated)

No new dependencies required.

### File Structure

```
app/
  routers/
    qbo_oauth.py      # New: OAuth connect, callback, disconnect, refresh
  services/
    qbo_service.py    # Existing: Add get_company_by_code method
  templates/
    admin/
      companies.html  # New: Companies management page
      base.html       # Existing: Extend for admin pages
```

---

## Appendix

### Related Documents

- [Phase 1 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-81-phase1-core-infrastructure.md)
- [Phase 2 PRD](/Users/burke/projects/fpqbo/docs/PRD/FOR-82-phase2-admin-authentication.md)
- [Linear Issue FOR-83](https://linear.app/fortiumpartners/issue/FOR-83/phase-3-qbo-oauth-token-management)

### Phase Dependencies

```
Phase 1 (Core) -----> Phase 2 (Admin Auth) -----> Phase 3 (This PRD - QBO OAuth)
                                                         |
                                                         v
                                                   Phase 4 (API Keys)
```

Phase 3 depends on:
- Phase 1: Database models (qbo_companies), config, FastAPI app
- Phase 2: Admin authentication (session validation, protected routes)

Phase 4 will depend on Phase 3 for working QBO company connections.

### Checklist for Phase 3 Completion

- [ ] QBO OAuth configuration in settings (QBO_CLIENT_ID, QBO_CLIENT_SECRET)
- [ ] OAuth connect endpoint (/api/qbo/connect)
- [ ] OAuth callback endpoint (/api/qbo/callback)
- [ ] State parameter validation (CSRF protection)
- [ ] Token exchange with Intuit
- [ ] Company Info API call for company name
- [ ] Company code auto-generation
- [ ] Database persistence of tokens
- [ ] Disconnect endpoint (/api/qbo/companies/{id}/disconnect)
- [ ] Manual refresh endpoint (/api/qbo/companies/{id}/refresh)
- [ ] Admin companies page (/admin/companies)
- [ ] Token status display logic
- [ ] Flash message handling for success/error
- [ ] Authentication requirement on all endpoints
- [ ] Error handling for OAuth failures
- [ ] .env.example updated with QBO OAuth instructions
- [ ] README.md updated with setup instructions
- [ ] Manual test: Complete OAuth flow succeeds
- [ ] Manual test: Token refresh works automatically
- [ ] Manual test: Disconnect clears tokens
- [ ] Manual test: Expired token triggers reconnect prompt
- [ ] Manual test: Unauthenticated access redirects to login

### Environment Variables Summary

Phase 3 adds/modifies these environment variables:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| QBO_CLIENT_ID | Yes | - | Intuit OAuth app client ID |
| QBO_CLIENT_SECRET | Yes | - | Intuit OAuth app client secret |
| QBO_REDIRECT_URI | No | {BASE_URL}/api/qbo/callback | OAuth callback URL |

### Intuit Developer Portal Setup

**Quick Setup Guide:**

1. Navigate to https://developer.intuit.com/
2. Sign in or create developer account
3. Dashboard > Create an app
4. Select "QuickBooks Online and Payments"
5. App name: "fortium-qbo"
6. Configure Keys & Credentials:
   - Development redirect URI: `http://localhost:8086/api/qbo/callback`
   - Production redirect URI: `https://your-domain.com/api/qbo/callback`
7. Scopes: Select "Accounting" (com.intuit.quickbooks.accounting)
8. Copy Client ID and Client Secret to .env
9. For production: Submit app for review

### Future Enhancements (Post-Phase 3)

1. **Token Encryption at Rest:**
   - Encrypt access/refresh tokens in database
   - Use application-level encryption key

2. **Webhook for Token Events:**
   - Notify admin when tokens expire
   - Email alerts for connection issues

3. **Multi-Company Selection:**
   - Let user select specific company during OAuth
   - Handle multiple companies per OAuth flow

4. **Connection Health Dashboard:**
   - Historical token refresh metrics
   - API request success rates per company

5. **Sandbox Environment Support:**
   - Toggle between sandbox and production
   - Separate credentials per environment

These are explicitly out of scope for Phase 3 but documented for future reference.
