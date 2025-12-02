# Fortium Partners QuickBooks Online Integration

**Project:** fpqbo - QuickBooks Online API Integration & Testing
**Purpose:** Direct QBO API access for testing, debugging, and building utilities
**Status:** Initial setup

## Overview

This project provides direct access to QuickBooks Online API for:
- Testing and debugging account balance lookups
- Understanding QBO API response structures
- Building reusable utilities for financial calculations
- Supporting n8n workflow development

## Setup

### Prerequisites
- Python 3.11+
- QuickBooks Online account with API access
- OAuth2 credentials from Intuit Developer Portal

### Environment
```bash
cd /Users/burke/projects/fpqbo
source venv/bin/activate
```

### Environment Variables (.env)
```
QBO_CLIENT_ID=your_client_id
QBO_CLIENT_SECRET=your_client_secret
QBO_COMPANY_ID=1208415120
QBO_REDIRECT_URI=https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl
QBO_ACCESS_TOKEN=your_access_token
QBO_REFRESH_TOKEN=your_refresh_token
QBO_REALM_ID=1208415120
```

## Account Structure (Fortium Partners)

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

## Key Scripts

- `qbo_client.py` - QBO API client with OAuth2 handling
- `trial_balance.py` - Fetch and parse Trial Balance report
- `test_accounts.py` - Test account lookup functions
- `refresh_token.py` - Refresh OAuth2 tokens

## Usage

```bash
# Activate environment
source venv/bin/activate

# Test API connection
python test_connection.py

# Fetch trial balance
python trial_balance.py

# Debug specific accounts
python test_accounts.py 310000 219500
```

## API Reference

### Trial Balance Endpoint
```
GET /v3/company/{companyId}/reports/TrialBalance
```

### Query Parameters
- `minorversion=65` - API version
- `start_date` / `end_date` - Date range (optional)
- `accounting_method` - Accrual or Cash

## Notes

- OAuth tokens expire after 1 hour; use refresh token to renew
- Company ID (Realm ID): 1208415120
- Parent accounts appear in Summary rows in Trial Balance response
- Child accounts appear in nested Rows.Row arrays
