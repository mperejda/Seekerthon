import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.routers import cherry, hackathons, mint, newsletter, projects, registrations, support_nft, votes, users
from app.middleware.auth import AuthMiddleware
from app.config import get_settings
from app import scheduler
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# httpx includes the complete request URL in its INFO message. RPC providers
# commonly authenticate through query parameters, so INFO logging can expose
# credentials in platform logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
api.include_router(cherry.router, prefix="/api/v1", tags=["cherry"])


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/icon.png")
async def app_icon():
    return FileResponse("app/static/icon.png", media_type="image/png")


app = CORSMiddleware(
    api,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
