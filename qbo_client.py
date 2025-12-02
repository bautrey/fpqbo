"""
QuickBooks Online API Client

Provides direct access to QBO API using OAuth2 tokens.
Can import tokens from n8n credentials or use standalone.
"""

import os
import json
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class QBOClient:
    """QuickBooks Online API Client"""

    BASE_URL = "https://quickbooks.api.intuit.com/v3/company"

    def __init__(self, access_token=None, company_id=None):
        self.access_token = access_token or os.getenv('QBO_ACCESS_TOKEN')
        self.company_id = company_id or os.getenv('QBO_COMPANY_ID', '1208415120')
        self.refresh_token = os.getenv('QBO_REFRESH_TOKEN')
        self.client_id = os.getenv('QBO_CLIENT_ID')
        self.client_secret = os.getenv('QBO_CLIENT_SECRET')

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def _url(self, endpoint):
        return f"{self.BASE_URL}/{self.company_id}/{endpoint}"

    def get(self, endpoint, params=None):
        """Make GET request to QBO API"""
        default_params = {'minorversion': '65'}
        if params:
            default_params.update(params)

        response = requests.get(
            self._url(endpoint),
            headers=self._headers(),
            params=default_params
        )

        if response.status_code == 401:
            raise Exception("Authentication failed - token may be expired. Refresh token or re-authenticate in n8n.")

        response.raise_for_status()
        return response.json()

    def get_trial_balance(self, start_date=None, end_date=None, accounting_method='Accrual'):
        """Fetch Trial Balance report"""
        params = {'accounting_method': accounting_method}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date

        return self.get('reports/TrialBalance', params)

    def get_balance_sheet(self, as_of_date=None, accounting_method='Accrual'):
        """Fetch Balance Sheet report"""
        params = {'accounting_method': accounting_method}
        if as_of_date:
            params['as_of_date'] = as_of_date

        return self.get('reports/BalanceSheet', params)

    def get_account(self, account_id):
        """Fetch a specific account by ID"""
        return self.get(f'account/{account_id}')

    def query(self, sql):
        """Execute a QBO query (SQL-like syntax)"""
        return self.get('query', {'query': sql})

    def get_all_accounts(self):
        """Fetch all accounts"""
        return self.query("SELECT * FROM Account MAXRESULTS 1000")


def get_client_from_n8n_credentials():
    """
    Extract OAuth tokens from n8n's credential storage.
    n8n stores encrypted credentials in PostgreSQL.

    For now, we'll need to manually copy tokens or use the API.
    """
    # This would require access to n8n's encryption key and database
    # For simplicity, use environment variables instead
    return QBOClient()


if __name__ == '__main__':
    # Quick test
    client = QBOClient()

    if not client.access_token:
        print("No access token found. Set QBO_ACCESS_TOKEN in .env")
        print("You can get tokens from:")
        print("  1. Intuit OAuth2 Playground: https://developer.intuit.com/app/developer/playground")
        print("  2. Your n8n QuickBooks credential (copy from n8n UI)")
        exit(1)

    print(f"Company ID: {client.company_id}")
    print("Testing API connection...")

    try:
        result = client.get_trial_balance()
        print(f"Success! Got {len(result.get('Rows', {}).get('Row', []))} rows")
    except Exception as e:
        print(f"Error: {e}")
