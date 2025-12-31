"""OAuth service for Google authentication."""

from authlib.integrations.starlette_client import OAuth

from app.config import settings

# Initialize OAuth registry
oauth = OAuth()


def get_oauth_client() -> OAuth:
    """
    Get configured OAuth client with Google provider.

    Configures Google OAuth with:
    - Client ID and secret from settings
    - OpenID Connect discovery for automatic endpoint configuration
    - Scopes: openid email profile

    Returns:
        Configured OAuth instance with Google provider
    """
    # Register Google OAuth provider (only once)
    if not hasattr(oauth, "google"):
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
            },
        )

    return oauth
