import os
import uuid
import mimetypes
import boto3
from botocore.config import Config

ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
BUCKET_NAME = os.environ["R2_BUCKET_NAME"]
# Public bucket URL — e.g. https://pub-xxx.r2.dev or your custom domain (no trailing slash)
PUBLIC_URL = os.environ["R2_PUBLIC_URL"].rstrip("/")

_PRESIGN_TTL = 300  # seconds


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def generate_upload_url(project_id: str, filename: str, content_type: str) -> tuple[str, str, str]:
    """Return (presigned_put_url, public_cdn_url, r2_key)."""
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        ext = mimetypes.guess_extension(content_type) or ""
    key = f"projects/{project_id}/{uuid.uuid4()}{ext}"

    upload_url = _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET_NAME, "Key": key, "ContentType": content_type},
        ExpiresIn=_PRESIGN_TTL,
    )
    return upload_url, f"{PUBLIC_URL}/{key}", key


def key_to_public_url(key: str) -> str:
    return f"{PUBLIC_URL}/{key}"
