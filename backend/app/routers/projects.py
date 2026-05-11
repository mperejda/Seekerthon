import os
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Query
from typing import List
from app.db import get_supabase_admin
from app.models.schemas import (
    ProjectCreate, ProjectResponse,
    AssetUploadUrlRequest, AssetUploadUrlResponse,
    AssetConfirmRequest, AssetConfirmResponse,
)
from app.services.r2_service import generate_upload_url, key_to_public_url

router = APIRouter()


@router.post("/", response_model=ProjectResponse)
async def submit_project(body: ProjectCreate, request: Request):
    db = get_supabase_admin()

    hackathon = db.table("hackathons").select("*").eq("id", str(body.hackathon_id)).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    h = hackathon.data
    if h["status"] not in ("open",):
        raise HTTPException(status_code=400, detail="Hackathon is not open for submissions")

    voting_start = datetime.fromisoformat(h["voting_start"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= voting_start:
        raise HTTPException(status_code=400, detail="Submission window has closed — voting has started")

    user_row = db.table("users").select("has_builder_pass").eq("id", request.state.user_id).maybe_single().execute()
    if not (user_row.data or {}).get("has_builder_pass", False):
        raise HTTPException(status_code=403, detail="Project submissions require an Alpine Labs Builder Pass")

    # Enforce max_projects limit
    existing_projects = db.table("projects").select("id") \
        .eq("hackathon_id", str(body.hackathon_id)).execute()
    if len(existing_projects.data) >= h["max_projects"]:
        raise HTTPException(status_code=409, detail="Hackathon has reached the maximum number of projects")

    # One project per team lead per hackathon
    existing = db.table("projects").select("id") \
        .eq("hackathon_id", str(body.hackathon_id)) \
        .eq("team_lead_id", request.state.user_id) \
        .execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="You already submitted a project to this hackathon")

    data = {
        **body.model_dump(mode="json", exclude={"hackathon_id"}),
        "hackathon_id": str(body.hackathon_id),
        "team_lead_id": request.state.user_id,
        "status": "submitted",
        "tech_stack": body.tech_stack,
    }
    result = db.table("projects").insert(data).execute()
    return ProjectResponse(**result.data[0])


def _get_project_or_403(db, project_id: str, user_id: str):
    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    return project.data


@router.post("/{project_id}/assets/upload-url", response_model=AssetUploadUrlResponse)
async def get_asset_upload_url(project_id: str, body: AssetUploadUrlRequest, request: Request):
    """Step 1: get a presigned R2 PUT URL. The client uploads the file directly to R2."""
    db = get_supabase_admin()
    _get_project_or_403(db, project_id, request.state.user_id)

    upload_url, public_url, key = generate_upload_url(project_id, body.filename, body.content_type)
    return AssetUploadUrlResponse(upload_url=upload_url, public_url=public_url, key=key)


@router.post("/{project_id}/assets/confirm", response_model=AssetConfirmResponse)
async def confirm_asset_upload(project_id: str, body: AssetConfirmRequest, request: Request):
    """Step 2: called after a successful R2 PUT. Saves the public URL to the project."""
    db = get_supabase_admin()
    project = _get_project_or_403(db, project_id, request.state.user_id)

    public_url = key_to_public_url(body.key)
    asset_urls = project.get("storage_asset_ids", []) + [public_url]
    db.table("projects").update({"storage_asset_ids": asset_urls}).eq("id", project_id).execute()
    return AssetConfirmResponse(public_url=public_url)


@router.get("/hackathon/{hackathon_id}", response_model=List[ProjectResponse])
async def list_projects(
    hackathon_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = get_supabase_admin()
    result = db.table("projects").select("*") \
        .eq("hackathon_id", hackathon_id) \
        .order("vote_count", desc=True) \
        .range(offset, offset + limit - 1) \
        .execute()
    return [ProjectResponse(**p) for p in result.data]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    db = get_supabase_admin()
    result = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**result.data)
