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
- To access QBO data, use the deployed API with an API key:
  ```bash
  curl -H "X-API-Key: <your-key>" https://qbo-oauth.onrender.com/api/invoices/
  ```
- Admin UI: https://qbo-oauth.onrender.com (requires @fortiumpartners.com Google login)

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

### Legacy Scripts (root directory)
These use the deprecated root `.env` and **no longer work**:
- `qbo_client_deprecated.py`, `trial_balance.py`, `refresh_token.py`, etc.
