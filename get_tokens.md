# Getting QuickBooks OAuth2 Tokens

## Option 1: Intuit OAuth2 Playground (Easiest)

1. Go to https://developer.intuit.com/app/developer/playground
2. Select your app (or create one)
3. Select "Accounting" scope
4. Click "Get Authorization Code"
5. Log in to QuickBooks and authorize
6. Click "Get Tokens"
7. Copy the Access Token and Refresh Token

## Option 2: Copy from n8n

1. Open n8n at http://localhost:5678
2. Go to Settings > Credentials
3. Click on "QuickBooks Online account"
4. The tokens are stored encrypted, but you can re-authenticate:
   - Click "Connect" to refresh the OAuth flow
   - After connecting, check browser dev tools Network tab
   - Look for the callback request to see tokens

## Option 3: Use n8n Workflow to Output Tokens

Create a simple n8n workflow:
1. Manual Trigger
2. Code node with:
```javascript
return [{
  json: {
    note: "Check n8n logs for token output",
    company_id: "1208415120"
  }
}];
```
3. HTTP Request to QBO API (this will use your saved credential)

Then check the n8n execution to see if token is logged.

## Setting Up .env

Once you have tokens, create `/Users/burke/projects/fpqbo/.env`:

```
QBO_CLIENT_ID=your_client_id
QBO_CLIENT_SECRET=your_client_secret
QBO_COMPANY_ID=1208415120
QBO_REALM_ID=1208415120
QBO_ACCESS_TOKEN=your_access_token_here
QBO_REFRESH_TOKEN=your_refresh_token_here
QBO_REDIRECT_URI=https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl
QBO_ENVIRONMENT=production
```

## Token Expiration

- Access tokens expire in 1 hour
- Refresh tokens expire in 100 days
- Use `refresh_token.py` to get new access tokens

## Getting Client ID/Secret

1. Go to https://developer.intuit.com
2. Click "My Apps" > Select your app
3. Go to "Keys & credentials"
4. Copy Client ID and Client Secret (Production keys for production data)
