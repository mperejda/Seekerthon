from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Query
from typing import List
from botocore.exceptions import ClientError
from app.constants import MAX_VIDEO_UPLOAD_BYTES
from app.db import get_supabase_admin
from app.models.schemas import (
    ProjectSubmit, ProjectResponse, RegistrationTxResponse, VerifyReleaseRequest,
    AssetUploadUrlRequest, AssetUploadUrlResponse, AssetConfirmRequest, AssetConfirmResponse,
    SubmitTxResponse, SubmitConfirmRequest,
)
from app.services.solana_service import (
    build_mark_submitted_transaction,
    derive_project_record_pda,
    verify_program_transaction_on_chain,
)
from app.services import r2_service
from app.services import moderation_service

router = APIRouter()


@router.patch("/{project_id}/submit", response_model=SubmitTxResponse)
async def submit_project_details(project_id: str, body: ProjectSubmit, request: Request):
    """
    Save project details and, for escrow hackathons, return a partially-signed
    mark_submitted transaction for the user to sign.  The user is the fee payer so
    the backend wallet never needs SOL.  Call POST /submit/confirm with the
    resulting signature to finalize status → 'submitted'.

    For non-escrow hackathons the project is marked submitted immediately and
    transaction_b64 is null.
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

    # For escrow hackathons keep status='registered' until the on-chain tx is confirmed.
    new_status = "registered" if escrow_pubkey else "submitted"
    result = db.table("projects").update({
        "name": body.name.strip(),
        "description": body.description,
        "demo_url": body.demo_url,
        "repo_url": body.repo_url,
        "tech_stack": body.tech_stack,
        "status": new_status,
    }).eq("id", project_id).execute()

    proj = ProjectResponse(**result.data[0])

    if not escrow_pubkey:
        return SubmitTxResponse(project=proj)

    try:
        tx_b64 = await build_mark_submitted_transaction(
            user_wallet=request.state.wallet_address,
            hackathon_id_str=p["hackathon_id"],
            escrow_pda=escrow_pubkey,
            project_id_str=project_id,
        )
    except BaseException as exc:
        db.table("projects").update({"status": "registered"}).eq("id", project_id).execute()
        raise HTTPException(status_code=500, detail=f"Failed to build submit transaction — please retry: {exc}")
    return SubmitTxResponse(transaction_b64=tx_b64, project=proj)


@router.post("/{project_id}/submit/confirm", response_model=ProjectResponse)
async def confirm_submit(project_id: str, body: SubmitConfirmRequest, request: Request):
    """
    Verify the mark_submitted transaction landed on-chain and flip the project
    to 'submitted' so it appears on the leaderboard.
    """
    db = get_supabase_admin()

    project = db.table("projects").select("*").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    p = project.data

    if str(p["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    if p["status"] != "registered":
        raise HTTPException(status_code=409, detail=f"Project is already '{p['status']}'")

    hackathon = db.table("hackathons").select("escrow_pubkey").eq("id", p["hackathon_id"]).single().execute()
    escrow_pubkey = hackathon.data.get("escrow_pubkey") if hackathon.data else None

    if escrow_pubkey:
        project_record_pda = derive_project_record_pda(escrow_pubkey, project_id)
        verified = await verify_program_transaction_on_chain(
            body.tx_signature,
            request.state.wallet_address,
            [escrow_pubkey, project_record_pda],
            "mark_submitted",
        )
        if not verified:
            raise HTTPException(status_code=400, detail="mark_submitted not confirmed on-chain — please retry")

    result = db.table("projects").update({"status": "submitted"}).eq("id", project_id).execute()
    return ProjectResponse(**result.data[0])


@router.post("/{project_id}/video-upload-url", response_model=AssetUploadUrlResponse)
async def get_video_upload_url(project_id: str, body: AssetUploadUrlRequest, request: Request):
    """Return a presigned PUT URL so the client can upload an MP4 directly to R2."""
    db = get_supabase_admin()
    project = db.table("projects").select("team_lead_id,status").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    if project.data["status"] == "disqualified":
        raise HTTPException(status_code=403, detail="This project has been disqualified")
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
    project = db.table("projects").select("team_lead_id,status").eq("id", project_id).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.data["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    if project.data["status"] == "disqualified":
        raise HTTPException(status_code=403, detail="This project has been disqualified")

    expected_prefix = f"projects/{project_id}/"
    if not body.key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="Invalid video upload key")

    try:
        metadata = r2_service.head_object(body.key)
    except ClientError:
        raise HTTPException(status_code=400, detail="Uploaded video was not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not validate uploaded video: {exc}")

    size = int(metadata.get("ContentLength") or 0)
    content_type = (metadata.get("ContentType") or "").split(";", 1)[0].strip().lower()
    if size <= 0:
        raise HTTPException(status_code=400, detail="Uploaded video is empty")
    if size > MAX_VIDEO_UPLOAD_BYTES:
        try:
            r2_service.delete_object(body.key)
        except Exception:
            pass
        raise HTTPException(status_code=413, detail="Demo video must be 50MB or smaller")
    if content_type != "video/mp4":
        try:
            r2_service.delete_object(body.key)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Only video/mp4 uploads are supported")

    safe = await moderation_service.is_video_safe(body.key)
    if not safe:
        try:
            r2_service.delete_object(body.key)
        except Exception:
            pass
        db.table("projects").update({"status": "disqualified", "video_url": None}).eq("id", project_id).execute()
        raise HTTPException(
            status_code=422,
            detail="Your video was flagged by our content moderation system. Your registration has been cancelled.",
        )

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
