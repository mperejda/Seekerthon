import os
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from typing import List
from app.constants import PROJECT_SUBMISSION_LIMIT
from app.db import get_supabase_admin
from app.models.schemas import ProjectCreate, ProjectResponse, RegistrationTxResponse, VerifyReleaseRequest
from app.services.solana_service import (
    build_register_project_transaction,
    derive_project_record_pda,
    verify_program_transaction_on_chain,
)

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
        "status": "pending_registration" if h.get("escrow_pubkey") else "submitted",
        "tech_stack": body.tech_stack,
    }
    result = db.table("projects").insert(data).execute()
    return ProjectResponse(**result.data[0])


@router.get("/{project_id}/register-tx", response_model=RegistrationTxResponse)
async def prepare_project_registration(project_id: str, request: Request):
    db = get_supabase_admin()
    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")

    hackathon = db.table("hackathons").select("*").eq("id", project.data["hackathon_id"]).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    if not hackathon.data.get("escrow_pubkey"):
        raise HTTPException(status_code=400, detail="Escrow not set up for this hackathon")

    tx_b64, project_record = await build_register_project_transaction(
        request.state.wallet_address,
        hackathon.data["escrow_pubkey"],
        project_id,
    )
    return RegistrationTxResponse(transaction_b64=tx_b64, project_record_pda=project_record)


@router.post("/{project_id}/register", response_model=ProjectResponse)
async def confirm_project_registration(project_id: str, body: VerifyReleaseRequest, request: Request):
    if not body.tx_signature:
        raise HTTPException(status_code=400, detail="tx_signature required")

    db = get_supabase_admin()
    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")

    hackathon = db.table("hackathons").select("*").eq("id", project.data["hackathon_id"]).single().execute()
    if not hackathon.data or not hackathon.data.get("escrow_pubkey"):
        raise HTTPException(status_code=400, detail="Escrow not set up for this hackathon")

    project_record = derive_project_record_pda(hackathon.data["escrow_pubkey"], project_id)
    verified = await verify_program_transaction_on_chain(
        body.tx_signature,
        request.state.wallet_address,
        [hackathon.data["escrow_pubkey"], project_record],
    )
    if not verified:
        raise HTTPException(status_code=400, detail="Project registration transaction not confirmed on-chain")

    result = db.table("projects").update({
        "status": "submitted",
        "onchain_pda": project_record,
    }).eq("id", project_id).execute()
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
