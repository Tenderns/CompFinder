"""Access token checks: AI clients send it as a Bearer header, the browser keeps a cookie derived from it."""
import hashlib
import hmac

COOKIE = "compfinder_session"
OPEN_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}


def protected(path):
    if path in OPEN_PATHS:
        return False
    # The page shell and its assets stay public; everything with data or actions needs the token.
    return path.startswith(("/api/", "/docs")) or path in {"/mcp", "/redoc", "/openapi.json"}


def session_value(token):
    # Changing the token invalidates every browser session.
    return hmac.new(token.encode(), b"compfinder-browser-session", hashlib.sha256).hexdigest()


def same(given, expected):
    return hmac.compare_digest(given.encode(), expected.encode())


def bearer(request):
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def has_bearer(request, token):
    return same(bearer(request), token)


def has_cookie(request, token):
    return same(request.cookies.get(COOKIE, ""), session_value(token))
