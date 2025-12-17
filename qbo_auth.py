#!/usr/bin/env python3
"""
QuickBooks Online Authentication Manager

Handles token refresh and provides simple CLI for auth management.

Usage:
    python3 qbo_auth.py status    # Check token status
    python3 qbo_auth.py refresh   # Refresh access token
    python3 qbo_auth.py auth      # Start full OAuth flow
    python3 qbo_auth.py test      # Test API connection
"""

import os
import sys
import subprocess
from base64 import b64encode
from datetime import datetime
from dotenv import load_dotenv, set_key
import requests

load_dotenv()

ENV_FILE = os.path.join(os.path.dirname(__file__), '.env')
TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
API_BASE = 'https://quickbooks.api.intuit.com/v3/company'


def get_credentials():
    """Load credentials from environment"""
    return {
        'client_id': os.getenv('QBO_CLIENT_ID'),
        'client_secret': os.getenv('QBO_CLIENT_SECRET'),
        'access_token': os.getenv('QBO_ACCESS_TOKEN'),
        'refresh_token': os.getenv('QBO_REFRESH_TOKEN'),
        'company_id': os.getenv('QBO_COMPANY_ID', '1208415120'),
    }


def refresh_tokens():
    """Refresh access token using refresh token"""
    creds = get_credentials()

    if not creds['refresh_token']:
        print("ERROR: No refresh token found. Run 'python3 qbo_auth.py auth' first.")
        return False

    credentials = b64encode(
        f"{creds['client_id']}:{creds['client_secret']}".encode()
    ).decode()

    response = requests.post(
        TOKEN_URL,
        headers={
            'Accept': 'application/json',
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={
            'grant_type': 'refresh_token',
            'refresh_token': creds['refresh_token']
        }
    )

    if response.status_code != 200:
        error_data = response.json() if response.text else {}
        error = error_data.get('error', 'unknown')
        desc = error_data.get('error_description', response.text)

        if error == 'invalid_grant':
            print(f"ERROR: Refresh token expired or invalid.")
            print(f"Run 'python3 qbo_auth.py auth' to re-authorize.")
            return False
        else:
            print(f"ERROR: Token refresh failed: {error} - {desc}")
            return False

    tokens = response.json()

    # Save new tokens
    set_key(ENV_FILE, 'QBO_ACCESS_TOKEN', tokens['access_token'])
    set_key(ENV_FILE, 'QBO_REFRESH_TOKEN', tokens['refresh_token'])

    # Reload environment
    load_dotenv(override=True)

    print("✓ Tokens refreshed successfully!")
    print(f"  Access token expires in: {tokens.get('expires_in', 'N/A')} seconds")
    return True


def test_connection():
    """Test API connection with current tokens"""
    creds = get_credentials()

    if not creds['access_token']:
        print("ERROR: No access token found.")
        return False

    url = f"{API_BASE}/{creds['company_id']}/companyinfo/{creds['company_id']}"

    response = requests.get(
        url,
        headers={
            'Authorization': f"Bearer {creds['access_token']}",
            'Accept': 'application/json'
        },
        params={'minorversion': '65'}
    )

    if response.status_code == 401:
        print("✗ Access token expired or invalid")
        print("  Try: python3 qbo_auth.py refresh")
        return False
    elif response.status_code != 200:
        print(f"✗ API error: {response.status_code}")
        print(f"  {response.text[:200]}")
        return False

    data = response.json()
    company = data.get('CompanyInfo', {})
    print("✓ API connection successful!")
    print(f"  Company: {company.get('CompanyName', 'N/A')}")
    print(f"  Company ID: {creds['company_id']}")
    return True


def show_status():
    """Show current authentication status"""
    creds = get_credentials()

    print("\nQuickBooks Online Authentication Status")
    print("=" * 50)
    print(f"Client ID:     {creds['client_id'][:20]}..." if creds['client_id'] else "Client ID:     NOT SET")
    print(f"Client Secret: {'*' * 20}" if creds['client_secret'] else "Client Secret: NOT SET")
    print(f"Company ID:    {creds['company_id']}")
    print(f"Access Token:  {creds['access_token'][:30]}..." if creds['access_token'] else "Access Token:  NOT SET")
    print(f"Refresh Token: {creds['refresh_token'][:20]}..." if creds['refresh_token'] else "Refresh Token: NOT SET")
    print()

    # Test connection
    if creds['access_token']:
        test_connection()


def start_auth():
    """Start OAuth authorization flow"""
    print("Starting OAuth authorization server...")
    script_dir = os.path.dirname(__file__)
    oauth_script = os.path.join(script_dir, 'oauth_server.py')
    subprocess.run([sys.executable, oauth_script])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == 'status':
        show_status()
    elif command == 'refresh':
        refresh_tokens()
    elif command == 'auth':
        start_auth()
    elif command == 'test':
        test_connection()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == '__main__':
    main()
