import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from app.routers import hackathons, mint, newsletter, projects, registrations, support_nft, votes, users
from app.middleware.auth import AuthMiddleware
from app.config import get_settings
from app import scheduler
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


api = FastAPI(
    title="Seeker Hackathon API",
    description="Backend for the Seeker Hackathon voting platform",
    version="1.0.0",
    lifespan=lifespan,
)

api.add_middleware(AuthMiddleware)

api.include_router(users.router, prefix="/api/v1/users", tags=["users"])
api.include_router(hackathons.router, prefix="/api/v1/hackathons", tags=["hackathons"])
api.include_router(registrations.router, prefix="/api/v1/hackathons", tags=["registrations"])
api.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
api.include_router(votes.router, prefix="/api/v1/votes", tags=["votes"])
api.include_router(mint.router, prefix="/api/v1/mint", tags=["mint"])
api.include_router(newsletter.router, prefix="/api/v1", tags=["newsletter"])
api.include_router(support_nft.router, prefix="/api/v1/support-nft", tags=["support-nft"])
api.include_router(support_nft.router, prefix="/api/v1", tags=["support-nft-metadata"])


@api.get("/health")
async def health():
    return {"status": "ok"}


_PUBLIC_CORS = CORSMiddleware(
    api,
    allow_origins=["https://seekerthon.com", "https://app.seekerthon.com"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
_RESTRICTED_CORS = CORSMiddleware(
    api,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

_PUBLIC_PATHS = ("/api/v1/newsletter",)


class _CORSDispatcher:
    def __init__(self, public: ASGIApp, restricted: ASGIApp) -> None:
        self._public = public
        self._restricted = restricted

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        handler = self._public if any(path.startswith(p) for p in _PUBLIC_PATHS) else self._restricted
        await handler(scope, receive, send)


app = _CORSDispatcher(_PUBLIC_CORS, _RESTRICTED_CORS)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
