# Fortium Partners QuickBooks Online Integration

**Project:** fpqbo - QuickBooks Online API Integration & Testing
**Status:** Production (deployed on Render)

## Architecture

The `fortium-qbo/` directory contains a FastAPI service deployed at **https://qbo-oauth.onrender.com** that:
- Manages OAuth2 tokens for multiple QBO companies in a Supabase PostgreSQL database
- Auto-refreshes tokens via a background scheduler (every 45 minutes)
- Exposes a REST API for QBO data access (invoices, accounts, vendors, etc.)
- Provides an admin UI for managing connected companies (Google OAuth login)

### Connected Companies
| Code | Company | Region |
|------|---------|--------|
| FOR-138 | Fortium Partners, LP. | US |
| FOR-971 | Fortium Partners Canada LP | CA |

### IMPORTANT: Token Management
- **DO NOT** use the root `.env` file for QBO access — those credentials are from a deprecated Intuit app
- Tokens are managed automatically by the deployed service's background scheduler
- Admin UI: https://qbo-oauth.onrender.com (requires @fortiumpartners.com Google login)

### API Keys (macOS Keychain)
All `/api/*` endpoints require an `X-API-Key` header. Keys are stored in macOS Keychain:

```bash
# US company (FOR-138) — "Pipeline" key, works for most queries
security find-generic-password -a "burkestudio" -s "fpqbo-api-key-us" -w

# Canada company (FOR-971)
security find-generic-password -a "burkestudio" -s "fpqbo-api-key-ca" -w
```

**Usage:**
```bash
API_KEY=$(security find-generic-password -a "burkestudio" -s "fpqbo-api-key-us" -w)
curl -s -H "X-API-Key: $API_KEY" "https://qbo-oauth.onrender.com/api/invoices/"
curl -s -H "X-API-Key: $API_KEY" "https://qbo-oauth.onrender.com/api/accounts/"
```

To create new API keys, use the admin UI or `POST /admin/api-keys/` (requires admin session).

## API Endpoints

All `/api/*` endpoints require `X-API-Key` header.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/companies/` | List companies for API key |
| GET | `/api/invoices/` | List invoices |
| GET | `/api/invoices/by-doc-number/{doc_number}` | Get invoice by doc number |
| GET | `/api/customers/` | List customers |
| GET | `/api/vendors/` | List vendors |
| GET | `/api/accounts/` | Chart of accounts |
| GET | `/api/bills/` | List bills |
| GET | `/api/payments/` | List payments |
| GET | `/api/bill-payments/` | List bill payments |
| GET | `/api/credit-memos/` | List credit memos |
| GET | `/api/deposits/` | List deposits |
| GET | `/api/estimates/` | List estimates |
| GET | `/api/journal-entries/` | List journal entries |
| GET | `/api/purchases/` | List purchases |
| GET | `/api/purchase-orders/` | List purchase orders |
| GET | `/api/refund-receipts/` | List refund receipts |
| GET | `/api/sales-receipts/` | List sales receipts |
| GET | `/api/transfers/` | List transfers |
| GET | `/api/vendor-credits/` | List vendor credits |
| GET | `/api/items/` | List items |
| GET | `/api/employees/` | List employees |
| GET | `/api/departments/` | List departments |
| GET | `/api/time-activities/` | List time activities |
| GET | `/api/company/info` | Company info |
| GET | `/api/company/preferences` | Company preferences |
| GET | `/api/tax/agencies` | List tax agencies |
| GET | `/api/tax/codes` | List tax codes |
| GET | `/api/tax/rates` | List tax rates |
| GET | `/api/reference/currencies` | List company currencies |
| GET | `/api/reference/exchange-rates` | List exchange rates |
| GET | `/api/reference/payment-methods` | List payment methods |
| GET | `/api/reference/terms` | List terms |
| GET | `/api/reference/classes` | List tracking classes |
| GET | `/api/reference/customer-types` | List customer types |
| GET | `/api/attachments/` | List attachments |
| GET | `/api/recurring-transactions/` | List recurring transactions |
| GET | `/api/reports/trial-balance` | Trial Balance report |
| GET | `/api/reports/balance-sheet` | Balance Sheet report |
| GET | `/api/reports/profit-and-loss` | P&L report |
| GET | `/api/reports/general-ledger` | General Ledger report |
| POST | `/api/customers/` | Create a customer |
| POST | `/api/vendors/` | Create a vendor |
| POST | `/api/bills/` | Create a bill |
| POST | `/api/bills/{bill_id}` | Update a bill (sparse update) |
| POST | `/api/bill-payments/` | Create a bill payment (also applies VendorCredit via `LinkedTxn`) |
| POST | `/api/vendor-credits/` | Create a vendor credit |
| POST | `/api/journal-entries/` | Create a journal entry |
| POST | `/api/journal-entries/{id}/void` | Void a journal entry |
| DELETE | `/api/bills/{bill_id}` | Delete a bill |
| DELETE | `/api/invoices/{invoice_id}` | Delete an invoice |

All list endpoints also have `GET /{id}` variants for fetching by ID (except exchange rates, company info, and preferences).

## Account Structure (Fortium Partners US)

### Capital Accounts
- **310000** - Paid-In Capital (liability parent)
- **311xxx** - Individual partner capital accounts (children of 310000)
- **100000** - Capital Chase Checking (coverage)
- **105001** - Capital JPMorgan MM (coverage)

### Withholding Accounts
- **219500** - Additional Partner Withholding (liability parent)
- **260xxx** - Individual partner withholding accounts (children of 219500)
- **101000** - Withholding Chase Checking (coverage)
- **105002** - Withholding JPMorgan MM (coverage)

### Other Accounts
- **214000** - GP Distribution Owed
- **104000** - Operating Chase Checking

## Development

```bash
cd fortium-qbo
source ../venv/bin/activate
uvicorn app.main:app --reload
```

### Running tests

`pytest` and `pytest-asyncio` live in `fortium-qbo/requirements-dev.txt` (transitively pulls in `requirements.txt`). The test suite imports `app.config.Settings()`, which validates `APP_SECRET_KEY` (min 32 chars), `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET` at import time, so they must be set even though tests stub all network calls.

From the repo root with the root venv activated:

```bash
source venv/bin/activate
pip install -r fortium-qbo/requirements-dev.txt   # one-time
APP_SECRET_KEY=$(python3 -c "print('a'*32)") \
  GOOGLE_CLIENT_ID=test \
  GOOGLE_CLIENT_SECRET=test \
  pytest fortium-qbo/tests/ -v
```

CI (`.github/workflows/ci.yml`) sets the same dummies on the `test` job. Render deploys are handled by Render's own GitHub auto-deploy (the workflow no longer pings a deploy hook).

### Legacy Scripts (root directory)
These use the deprecated root `.env` and **no longer work**:
- `qbo_client_deprecated.py`, `trial_balance.py`, `refresh_token.py`, etc.
