from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from jose import jwt, JWTError
from app.config import get_settings
import re

_settings = get_settings()

EXEMPT_PATHS = {"/health", "/api/v1/users/challenge", "/api/v1/users/login", "/docs", "/openapi.json"}

PUBLIC_GET_PATHS = {
    "/api/v1/hackathons",
    "/api/v1/hackathons/",
}

PUBLIC_GET_PATTERNS = (
    re.compile(r"^/api/v1/hackathons/[^/]+$"),
    re.compile(r"^/api/v1/hackathons/[^/]+/leaderboard$"),
    re.compile(r"^/api/v1/hackathons/[^/]+/registration$"),
    re.compile(r"^/api/v1/projects/[^/]+$"),
    re.compile(r"^/api/v1/projects/hackathon/[^/]+$"),
)


def _is_public_get(path: str) -> bool:
    return path in PUBLIC_GET_PATHS or any(pattern.match(path) for pattern in PUBLIC_GET_PATTERNS)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        is_public = (
            request.url.path in EXEMPT_PATHS
            or request.method == "OPTIONS"
            or (request.method == "GET" and _is_public_get(request.url.path))
        )

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
            try:
                payload = jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
                request.state.user_id = payload["sub"]
                request.state.wallet_address = payload.get("wallet")
            except JWTError:
                if not is_public:
                    return JSONResponse({"detail": "Invalid token"}, status_code=401)
        elif not is_public:
            return JSONResponse({"detail": "Missing auth token"}, status_code=401)

        return await call_next(request)
