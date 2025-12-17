#!/usr/bin/env python3
"""
QuickBooks Online OAuth2 Server with ngrok support

A local server that handles the complete OAuth2 flow using ngrok for the callback:
1. Starts ngrok tunnel to get public URL
2. Opens browser to Intuit authorization page
3. Receives callback with authorization code
4. Exchanges code for access/refresh tokens
5. Saves tokens to .env file

Usage:
    python3 oauth_server.py

Requirements:
    pip install flask python-dotenv requests pyngrok
    ngrok installed and authenticated (ngrok config add-authtoken YOUR_TOKEN)
"""

import os
import sys
import webbrowser
import secrets
import json
from urllib.parse import urlencode
from base64 import b64encode
from threading import Timer
from dotenv import load_dotenv, set_key
import requests

try:
    from flask import Flask, request, redirect
except ImportError:
    print("Installing flask...")
    os.system(f"{sys.executable} -m pip install flask")
    from flask import Flask, request, redirect

try:
    from pyngrok import ngrok, conf
except ImportError:
    print("Installing pyngrok...")
    os.system(f"{sys.executable} -m pip install pyngrok")
    from pyngrok import ngrok, conf

load_dotenv()

# Configuration
CLIENT_ID = os.getenv('QBO_CLIENT_ID')
CLIENT_SECRET = os.getenv('QBO_CLIENT_SECRET')
LOCAL_PORT = 8080
SCOPE = 'com.intuit.quickbooks.accounting'
ENV_FILE = os.path.join(os.path.dirname(__file__), '.env')

# Intuit OAuth endpoints
AUTH_URL = 'https://appcenter.intuit.com/connect/oauth2'
TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'

app = Flask(__name__)
state_token = secrets.token_urlsafe(32)
ngrok_url = None


@app.route('/')
def index():
    """Start the OAuth flow"""
    redirect_uri = f"{ngrok_url}/callback"

    params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'scope': SCOPE,
        'redirect_uri': redirect_uri,
        'state': state_token
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print(f"\n→ Redirecting to Intuit authorization...")
    print(f"  Redirect URI: {redirect_uri}")

    return redirect(auth_url)


@app.route('/callback')
@app.route('/rest/oauth2-credential/callback')  # Match n8n's registered path
def callback():
    """Handle OAuth callback"""
    redirect_uri = f"{ngrok_url}/callback"

    # Verify state
    if request.args.get('state') != state_token:
        return "State mismatch - possible CSRF attack", 400

    # Check for errors
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', '')
        print(f"\n✗ Authorization error: {error}")
        print(f"  {error_desc}")
        return f"""
        <html>
        <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto;">
            <h1 style="color: red;">Authorization Error</h1>
            <p><strong>Error:</strong> {error}</p>
            <p>{error_desc}</p>
            <p>Make sure the redirect URI is registered in your Intuit app:</p>
            <code>{redirect_uri}</code>
        </body>
        </html>
        """, 400

    # Get authorization code
    code = request.args.get('code')
    realm_id = request.args.get('realmId')

    if not code:
        return "No authorization code received", 400

    print(f"\n✓ Received authorization code")
    print(f"  Company ID (realmId): {realm_id}")

    # Exchange code for tokens
    credentials = b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    response = requests.post(
        TOKEN_URL,
        headers={
            'Accept': 'application/json',
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri
        }
    )

    if response.status_code != 200:
        error_text = response.text
        print(f"\n✗ Token exchange failed: {response.status_code}")
        print(f"  {error_text}")
        return f"Token exchange failed: {response.status_code} - {error_text}", 400

    tokens = response.json()
    access_token = tokens['access_token']
    refresh_token = tokens['refresh_token']

    print(f"\n✓ Tokens received!")

    # Save to .env file
    set_key(ENV_FILE, 'QBO_ACCESS_TOKEN', access_token)
    set_key(ENV_FILE, 'QBO_REFRESH_TOKEN', refresh_token)
    if realm_id:
        set_key(ENV_FILE, 'QBO_COMPANY_ID', realm_id)
        set_key(ENV_FILE, 'QBO_REALM_ID', realm_id)

    print(f"✓ Tokens saved to .env")

    # Schedule shutdown
    Timer(2.0, shutdown_server).start()

    return f"""
    <html>
    <head><title>QBO OAuth Success</title></head>
    <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 20px;">
        <h1 style="color: green;">✓ Authorization Successful!</h1>
        <p>Tokens have been saved to <code>.env</code></p>
        <ul>
            <li><strong>Company ID:</strong> {realm_id}</li>
            <li><strong>Access Token:</strong> {access_token[:50]}...</li>
            <li><strong>Refresh Token:</strong> {refresh_token[:30]}...</li>
            <li><strong>Expires In:</strong> {tokens.get('expires_in', 'N/A')} seconds</li>
        </ul>
        <p>You can close this window and use the QBO API now.</p>
        <p><em>Server shutting down...</em></p>
    </body>
    </html>
    """


def shutdown_server():
    """Shutdown the Flask server and ngrok"""
    print("\nShutting down...")
    ngrok.kill()
    os._exit(0)


def open_browser(url):
    """Open browser after server starts"""
    webbrowser.open(url)


def start_ngrok():
    """Start ngrok tunnel and return public URL"""
    global ngrok_url

    # Start ngrok tunnel
    tunnel = ngrok.connect(LOCAL_PORT, "http")
    ngrok_url = tunnel.public_url

    # Ensure HTTPS
    if ngrok_url.startswith('http://'):
        ngrok_url = ngrok_url.replace('http://', 'https://')

    return ngrok_url


if __name__ == '__main__':
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: QBO_CLIENT_ID and QBO_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    print("=" * 70)
    print("QuickBooks Online OAuth2 Authorization (with ngrok)")
    print("=" * 70)

    print(f"\nClient ID: {CLIENT_ID[:20]}...")
    print(f"Local Port: {LOCAL_PORT}")

    print("\nStarting ngrok tunnel...")
    public_url = start_ngrok()
    callback_url = f"{public_url}/callback"

    print(f"\n" + "=" * 70)
    print("IMPORTANT: Add this redirect URI to your Intuit Developer App:")
    print("=" * 70)
    print(f"\n  {callback_url}\n")
    print("=" * 70)
    print("\nGo to: https://developer.intuit.com/app/developer/dashboard")
    print("→ Select your app → Keys & OAuth → Redirect URIs → Add URI")
    print("=" * 70)

    # Check for --auto flag to skip prompt (for non-interactive use)
    if '--auto' not in sys.argv:
        try:
            input("\nPress ENTER after adding the redirect URI to continue...")
        except EOFError:
            print("\n(Running in non-interactive mode, continuing automatically...)")
            print("Make sure you've added the redirect URI above to your Intuit app!")

    print(f"\nStarting local server...")
    print(f"Opening browser for authorization...")

    # Open browser after a short delay
    Timer(1.5, lambda: open_browser(f"{public_url}/")).start()

    # Run server
    app.run(host='0.0.0.0', port=LOCAL_PORT, debug=False)
