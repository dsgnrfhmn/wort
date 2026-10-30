"""Photo uploads for Texte: bytes from a browser are untrusted until Pillow has decoded them as a JPEG or a PNG.

The photo is only ever held in memory: read from the request, checked here, handed to text recognition (app/ocr.py)
and dropped with the request. No path, no file name (the browser's name is never used or shown) and nothing on disk
(CLAUDE.md, uploads: "then delete the image; only extracted text is stored").

Order of checks, cheapest first: size (before anything is decoded), declared type, magic bytes, size in pixels (from
the header, before the pixels are decoded), then the full decode. Anything else is refused with a message for the
user, never a stack trace and never part of the file.

Pillow is the optional "ocr" dependency group: without it nothing here works, and `available()` says so.
"""

from __future__ import annotations

import base64
import io

from app.i18n import t

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # the optional "ocr" group is not installed
    Image = None

MAX_BYTES = 20 * 1024 * 1024  # what the upload field promises ("up to 20 MB"); nginx allows 21 MB
MAX_PIXELS = 40_000_000  # width x height from the header: a 40 Mpx RGB photo is about 120 MB in memory
THUMB_SIDE = 1000  # the check step shows the photo this big (longer side)
DRAFT_SIDE = 3500  # a JPEG is decoded at a smaller scale (1/2, 1/4, 1/8) when it is much larger than text recognition needs

# declared type -> (magic bytes, the formats Pillow may name it; an iPhone JPEG with a depth map is an "MPO")
TYPES = {
    "image/jpeg": (b"\xff\xd8\xff", {"JPEG", "MPO"}),
    "image/png": (b"\x89PNG\r\n\x1a\n", {"PNG"}),
}


class UploadRejected(Exception):
    """The upload cannot be used. `message` is for the user (already in the interface language), `status` the HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def available() -> bool:
    return Image is not None


def read_image(raw: bytes, content_type: str):
    """The photo as a decoded, upright, opaque Pillow image (mode RGB or L), or UploadRejected."""
    if Image is None:
        raise UploadRejected(t("Text recognition is not set up on this server."), 503)
    if not raw:
        raise UploadRejected(t("The file is empty."))
    if len(raw) > MAX_BYTES:
        raise UploadRejected(t("The photo is larger than 20 MB."), 413)
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in TYPES:
        raise UploadRejected(t("Only JPG and PNG photos are accepted."))
    magic, formats = TYPES[declared]
    not_that = UploadRejected(t("This file is not a {kind} photo.", kind="JPG" if declared == "image/jpeg" else "PNG"))
    if not raw.startswith(magic):
        raise not_that
    try:
        image = Image.open(io.BytesIO(raw))  # reads the header only
        if image.format not in formats:
            raise not_that
        if image.width * image.height > MAX_PIXELS:
            raise UploadRejected(t("The photo is too large (more than 40 million pixels)."), 413)
        if image.format != "PNG":
            image.draft("RGB", (DRAFT_SIDE, DRAFT_SIDE))  # JPEG only: decode at a smaller scale if it is far bigger
        image.load()  # the full decode: a truncated or damaged file fails here
        image = ImageOps.exif_transpose(image)
    except UploadRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise UploadRejected(t("The photo could not be read. Is the file damaged?")) from None
    return _opaque(image)


def _opaque(image):
    """Transparency flattened onto white (a screenshot with an alpha channel), palette and CMYK made RGB."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image if image.mode in ("RGB", "L") else image.convert("RGB")


def thumbnail(image) -> str:
    """The photo for the check step: a small JPEG as a data URL, re-encoded (so without the camera's metadata) and sent
    in the page that shows it. Kept nowhere; the page it was sent in is the only copy."""
    small = image.convert("RGB")
    small.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    small.save(buffer, "JPEG", quality=70, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
