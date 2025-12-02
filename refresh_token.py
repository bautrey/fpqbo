"""
Refresh QuickBooks OAuth2 Token

Uses refresh token to get a new access token.
"""

import os
import requests
from base64 import b64encode
from dotenv import load_dotenv

load_dotenv()

def refresh_access_token():
    """Get new access token using refresh token"""

    client_id = os.getenv('QBO_CLIENT_ID')
    client_secret = os.getenv('QBO_CLIENT_SECRET')
    refresh_token = os.getenv('QBO_REFRESH_TOKEN')

    if not all([client_id, client_secret, refresh_token]):
        print("Missing required environment variables:")
        print(f"  QBO_CLIENT_ID: {'set' if client_id else 'MISSING'}")
        print(f"  QBO_CLIENT_SECRET: {'set' if client_secret else 'MISSING'}")
        print(f"  QBO_REFRESH_TOKEN: {'set' if refresh_token else 'MISSING'}")
        return None

    # Encode credentials for Basic auth
    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()

    response = requests.post(
        'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer',
        headers={
            'Accept': 'application/json',
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }
    )

    if response.status_code != 200:
        print(f"Error refreshing token: {response.status_code}")
        print(response.text)
        return None

    tokens = response.json()

    print("Token refreshed successfully!")
    print(f"\nNew Access Token (expires in {tokens.get('expires_in', 'unknown')} seconds):")
    print(tokens['access_token'][:50] + "...")
    print(f"\nNew Refresh Token:")
    print(tokens['refresh_token'][:50] + "...")

    print("\n\nUpdate your .env file with:")
    print(f"QBO_ACCESS_TOKEN={tokens['access_token']}")
    print(f"QBO_REFRESH_TOKEN={tokens['refresh_token']}")

    return tokens


if __name__ == '__main__':
    refresh_access_token()
