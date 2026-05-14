import os
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from typing import List
from app.db import get_supabase_admin
from app.models.schemas import (
    ProjectSubmit, ProjectResponse, RegistrationTxResponse, VerifyReleaseRequest,
    AssetUploadUrlRequest, AssetUploadUrlResponse, AssetConfirmRequest, AssetConfirmResponse,
)
from app.services.solana_service import send_mark_submitted_transaction
from app.services import r2_service

router = APIRouter()


@router.patch("/{project_id}/submit", response_model=ProjectResponse)
async def submit_project_details(project_id: str, body: ProjectSubmit, request: Request):
    """
    Fill in project details for a registered project (no wallet transaction needed).

    The project must be in 'registered' status (created during hackathon registration).
    After this call the project becomes 'submitted' and appears on the leaderboard.

    Prize eligibility is enforced by two on-chain checks inside claim_prize:
      1. The ProjectRecord PDA must exist (set at registration time — the allowlist check).
      2. The platform admin must have signed the claim certificate, which the backend
         only issues for projects with status='submitted' and a confirmed on-chain PDA.
    """
    db = get_supabase_admin()

    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    p = project.data

    if str(p["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    if p["status"] != "registered":
        raise HTTPException(
            status_code=409,
            detail=f"Project is already '{p['status']}' — can only submit from 'registered' status",
        )
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")

    hackathon = db.table("hackathons").select("status,voting_start,escrow_pubkey").eq("id", p["hackathon_id"]).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    h = hackathon.data

    if h["status"] != "open":
        raise HTTPException(status_code=400, detail="Hackathon is not open for submissions")
    voting_start = datetime.fromisoformat(h["voting_start"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= voting_start:
        raise HTTPException(status_code=400, detail="Submission window has closed — voting has started")

    escrow_pubkey = h.get("escrow_pubkey")

    result = db.table("projects").update({
        "name": body.name.strip(),
        "description": body.description,
        "demo_url": body.demo_url,
        "repo_url": body.repo_url,
        "tech_stack": body.tech_stack,
        "status": "submitted",
    }).eq("id", project_id).execute()

    if escrow_pubkey:
        try:
            await send_mark_submitted_transaction(
                hackathon_id_str=p["hackathon_id"],
                escrow_pda=escrow_pubkey,
                project_id_str=project_id,
            )
        except Exception as exc:
            # Roll back the DB update so DB and chain stay in sync.
            db.table("projects").update({"status": "registered"}).eq("id", project_id).execute()
            raise HTTPException(
                status_code=500,
                detail=f"On-chain mark_submitted failed — please retry: {exc}",
            )

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


@router.post("/{project_id}/video-upload-url", response_model=AssetUploadUrlResponse)
async def get_video_upload_url(project_id: str, body: AssetUploadUrlRequest, request: Request):
    """Return a presigned PUT URL so the client can upload an MP4 directly to R2."""
    db = get_supabase_admin()
    project = db.table("projects").select("team_lead_id").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    if body.content_type != "video/mp4":
        raise HTTPException(status_code=400, detail="Only video/mp4 uploads are supported")

    try:
        upload_url, public_url, key = r2_service.generate_upload_url(project_id, body.filename, body.content_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not generate upload URL: {exc}")

    return AssetUploadUrlResponse(upload_url=upload_url, public_url=public_url, key=key)


@router.post("/{project_id}/video-confirm", response_model=AssetConfirmResponse)
async def confirm_video_upload(project_id: str, body: AssetConfirmRequest, request: Request):
    """Record the R2 key as the project's video URL after a successful direct upload."""
    db = get_supabase_admin()
    project = db.table("projects").select("team_lead_id").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")

    public_url = r2_service.key_to_public_url(body.key)
    db.table("projects").update({"video_url": public_url}).eq("id", project_id).execute()
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
        .in_("status", ["submitted", "approved", "winner"]) \
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


# ── Deprecated endpoints ────────────────────────────────────────────────────
# Project registration now happens via GET/POST /hackathons/{id}/register-tx and /register.

@router.get("/{project_id}/register-tx", response_model=RegistrationTxResponse)
async def prepare_project_registration_deprecated(project_id: str, request: Request):
    raise HTTPException(
        status_code=410,
        detail="Use GET /hackathons/{hackathon_id}/register-tx instead. "
               "Registration now happens at hackathon enrolment time.",
    )


@router.post("/{project_id}/register", response_model=ProjectResponse)
async def confirm_project_registration_deprecated(project_id: str, body: VerifyReleaseRequest, request: Request):
    raise HTTPException(
        status_code=410,
        detail="Use POST /hackathons/{hackathon_id}/register instead. "
               "Registration now happens at hackathon enrolment time.",
    )
