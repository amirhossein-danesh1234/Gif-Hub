from dataclasses import dataclass
from pathlib import Path


class MediaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MediaType:
    extension: str
    content_type: str
    category: str


SIGNATURES: tuple[tuple[bytes, MediaType], ...] = (
    (b"\xff\xd8\xff", MediaType("jpg", "image/jpeg", "image")),
    (b"\x89PNG\r\n\x1a\n", MediaType("png", "image/png", "image")),
    (b"GIF87a", MediaType("gif", "image/gif", "animation")),
    (b"GIF89a", MediaType("gif", "image/gif", "animation")),
    (b"RIFF", MediaType("webp", "image/webp", "image")),
    (b"\x1a\x45\xdf\xa3", MediaType("webm", "video/webm", "video")),
)


def sniff_media_type(path: Path) -> MediaType:
    header = path.read_bytes()[:32]
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return MediaType("mp4", "video/mp4", "video")
    if header.startswith(b"RIFF") and b"WEBP" in header[:16]:
        return MediaType("webp", "image/webp", "image")
    for signature, media_type in SIGNATURES:
        if header.startswith(signature):
            return media_type
    raise MediaValidationError("Unsupported or invalid media MIME signature.")


def validate_upload_size(path: Path, max_upload_bytes: int) -> None:
    size = path.stat().st_size
    if size <= 0:
        raise MediaValidationError("Upload is empty.")
    if size > max_upload_bytes:
        raise MediaValidationError(f"Upload exceeds {max_upload_bytes} bytes.")
