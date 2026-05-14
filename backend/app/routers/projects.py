import os
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from typing import List
from app.constants import PROJECT_SUBMISSION_LIMIT
from app.db import get_supabase_admin
from app.models.schemas import ProjectCreate, ProjectResponse

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

    # Enforce the launch submission cap regardless of older per-hackathon settings.
    project_limit = min(h.get("max_projects") or PROJECT_SUBMISSION_LIMIT, PROJECT_SUBMISSION_LIMIT)
    existing_projects = db.table("projects").select("id") \
        .eq("hackathon_id", str(body.hackathon_id)).execute()
    if len(existing_projects.data) >= project_limit:
        raise HTTPException(
            status_code=409,
            detail=f"Hackathon has reached the maximum of {PROJECT_SUBMISSION_LIMIT} projects",
        )

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


@router.post("/{project_id}/assets")
async def upload_asset(project_id: str, file: UploadFile = File(...), request: Request = None):
    """Upload demo video or screenshot to Supabase Storage."""
    db = get_supabase_admin()
    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")

    ext = os.path.splitext(file.filename or "")[1].lower()
    safe_name = f"{uuid_module.uuid4()}{ext}"
    path = f"{project_id}/{safe_name}"

    content = await file.read()
    db.storage.from_("project-assets").upload(path, content, {"content-type": file.content_type})

    asset_ids = project.data.get("storage_asset_ids", []) + [path]
    db.table("projects").update({"storage_asset_ids": asset_ids}).eq("id", project_id).execute()
    return {"path": path}


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
