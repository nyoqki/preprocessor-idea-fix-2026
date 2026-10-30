import uuid

IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/heic": "heic",
}

SUPPORTED_FOR_RECOGNITION = frozenset({"image/jpeg", "image/png", "image/webp"})


def sniff_image_type(data: bytes) -> str:
    for signature, content_type in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"
    return "application/octet-stream"


def image_key(prefix: str, owner: int, content_type: str) -> str:
    return f"{prefix}/{owner}/{uuid.uuid4().hex}.{EXTENSIONS.get(content_type, 'bin')}"
