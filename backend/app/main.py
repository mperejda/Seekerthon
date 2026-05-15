import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import hackathons, mint, projects, registrations, votes, users
from app.middleware.auth import AuthMiddleware
from app.config import get_settings
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

_settings = get_settings()

api = FastAPI(
    title="Seeker Hackathon API",
    description="Backend for the Seeker Hackathon voting platform",
    version="1.0.0",
)

api.add_middleware(AuthMiddleware)

api.include_router(users.router, prefix="/api/v1/users", tags=["users"])
api.include_router(hackathons.router, prefix="/api/v1/hackathons", tags=["hackathons"])
api.include_router(registrations.router, prefix="/api/v1/hackathons", tags=["registrations"])
api.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
api.include_router(votes.router, prefix="/api/v1/votes", tags=["votes"])
api.include_router(mint.router, prefix="/api/v1/mint", tags=["mint"])


@api.get("/health")
async def health():
    return {"status": "ok"}


app = CORSMiddleware(
    api,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
