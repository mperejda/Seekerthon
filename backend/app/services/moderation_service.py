import io
import logging
import boto3
import av
from app.config import get_settings
from app.services import r2_service

_log = logging.getLogger(__name__)

_FRAMES_TO_SAMPLE = 8
_CONFIDENCE_THRESHOLD = 80.0


def _rekognition_client():
    s = get_settings()
    return boto3.client(
        "rekognition",
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=s.aws_secret_access_key,
        region_name=s.aws_region,
    )


def _extract_frames(video_bytes: bytes, n: int) -> list[bytes]:
    """Return up to n evenly-spaced JPEG frames from the video."""
    frames: list[bytes] = []
    container = av.open(io.BytesIO(video_bytes))
    try:
        stream = container.streams.video[0]
        total = stream.frames or 0
        step = max(1, total // n) if total >= n else 1
        for i, frame in enumerate(container.decode(stream)):
            if i % step == 0:
                buf = io.BytesIO()
                frame.to_image().save(buf, format="JPEG")
                frames.append(buf.getvalue())
            if len(frames) >= n:
                break
    finally:
        container.close()
    return frames


async def is_video_safe(r2_key: str) -> bool:
    """
    Download the video from R2, sample frames, and run AWS Rekognition
    DetectModerationLabels on each. Returns False if any frame is flagged.
    Returns True (safe) if AWS creds are not configured.
    """
    s = get_settings()
    if not s.aws_access_key_id:
        return True

    try:
        video_bytes = r2_service.download_bytes(r2_key)
    except Exception as exc:
        _log.error("moderation: failed to download video key=%s err=%s", r2_key, exc)
        return False

    try:
        frames = _extract_frames(video_bytes, _FRAMES_TO_SAMPLE)
    except Exception as exc:
        _log.error("moderation: frame extraction failed key=%s err=%s", r2_key, exc)
        return False

    client = _rekognition_client()
    for i, jpeg in enumerate(frames):
        try:
            resp = client.detect_moderation_labels(
                Image={"Bytes": jpeg},
                MinConfidence=_CONFIDENCE_THRESHOLD,
            )
            labels = resp.get("ModerationLabels", [])
            if labels:
                names = [l["Name"] for l in labels]
                _log.warning("moderation: unsafe frame %d key=%s labels=%s", i, r2_key, names)
                return False
        except Exception as exc:
            _log.error("moderation: rekognition error frame=%d key=%s err=%s", i, r2_key, exc)
            return False

    _log.info("moderation: PASSED %d frames scanned key=%s", len(frames), r2_key)
    return True
