import os
import uuid
import mimetypes
import boto3
from botocore.config import Config
from app.config import get_settings

_PRESIGN_TTL = 300  # seconds


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def generate_upload_url(project_id: str, filename: str, content_type: str) -> tuple[str, str, str]:
    """Return (presigned_put_url, public_cdn_url, r2_key). Only video/mp4 is accepted."""
    if content_type != "video/mp4":
        raise ValueError("Only video/mp4 uploads are supported")
    ext = os.path.splitext(filename)[1].lower() or ".mp4"
    key = f"projects/{project_id}/{uuid.uuid4()}{ext}"

    upload_url = _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().r2_bucket_name, "Key": key, "ContentType": content_type},
        ExpiresIn=_PRESIGN_TTL,
    )
    return upload_url, f"{get_settings().r2_public_url.rstrip('/')}/{key}", key


def key_to_public_url(key: str) -> str:
    return f"{get_settings().r2_public_url.rstrip('/')}/{key}"
