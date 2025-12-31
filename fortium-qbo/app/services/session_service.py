"""Session management service using signed cookies."""

from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings


def _get_serializer() -> URLSafeTimedSerializer:
    """Get URLSafeTimedSerializer instance with app secret key."""
    return URLSafeTimedSerializer(settings.app_secret_key.get_secret_value())


def create_session(email: str) -> str:
    """
    Create a signed session token for the given email.

    Args:
        email: User email address to encode in session

    Returns:
        Signed session token string
    """
    serializer = _get_serializer()
    return serializer.dumps(email, salt="session")


def verify_session(token: str) -> Optional[str]:
    """
    Verify a session token and extract the email.

    Args:
        token: Signed session token to verify

    Returns:
        Email if token is valid and not expired, None otherwise
    """
    serializer = _get_serializer()
    try:
        email = serializer.loads(
            token,
            salt="session",
            max_age=settings.session_max_age_seconds,
        )
        return email
    except (BadSignature, SignatureExpired):
        return None
