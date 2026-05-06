from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from jose import jwt, JWTError
from app.config import get_settings

_settings = get_settings()

EXEMPT_PATHS = {"/health", "/api/v1/users/challenge", "/api/v1/users/login", "/docs", "/openapi.json"}

PUBLIC_GET_PREFIXES = ("/api/v1/hackathons", "/api/v1/projects")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        is_public = (
            request.url.path in EXEMPT_PATHS
            or request.method == "OPTIONS"
            or (request.method == "GET" and request.url.path.startswith(PUBLIC_GET_PREFIXES))
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
