from __future__ import annotations

from io import BytesIO
from typing import Literal

from PIL import Image
from PIL.PngImagePlugin import PngInfo


def synthetic_image_bytes(
    image_format: Literal["JPEG", "PNG", "WEBP"] = "PNG",
    *,
    metadata: str | None = None,
    size: tuple[int, int] = (3, 2),
    color: tuple[int, int, int] = (32, 96, 160),
    orientation: int | None = None,
) -> bytes:
    """Encode a small synthetic image, optionally carrying synthetic private metadata."""
    exif = Image.Exif()
    if metadata is not None:
        exif[270] = metadata  # ImageDescription: synthetic test data only.
    if orientation is not None:
        exif[274] = orientation
    with Image.new("RGB", size, color) as source, BytesIO() as output:
        if image_format == "PNG":
            pnginfo = PngInfo()
            if metadata is not None:
                pnginfo.add_text("Comment", metadata)
            source.save(output, format="PNG", pnginfo=pnginfo, exif=exif)
        elif image_format == "JPEG":
            source.save(output, format="JPEG", quality=95, subsampling=0, exif=exif)
        else:
            source.save(output, format="WEBP", lossless=True, exif=exif)
        return output.getvalue()
