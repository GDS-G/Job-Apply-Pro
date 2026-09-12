"""Decode approved image inputs into bounded, metadata-free upload bytes.

This boundary deliberately produces only PNG. Revalidating an already normalized
part cannot introduce another lossy JPEG/WebP generation, so the gateway hashes
the same bytes that the provider receives. This is not visual-content redaction.
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO
from typing import Literal

from PIL import Image, ImageFile, UnidentifiedImageError

MAX_MEDIA_BYTES = 5_242_880
MAX_IMAGE_DIMENSION = 8_192
MAX_IMAGE_PIXELS = 16_777_216
NORMALIZED_MEDIA_MIME: Literal["image/png"] = "image/png"

_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_INVALID_IMAGE = "Media image is corrupt or incomplete"
_ORIENTATION_TRANSPOSES = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_JPEG_FRAME_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


class MediaNormalizationError(ValueError):
    """Safe, input-free validation failure for an uploaded image."""


class _BoundedOutput(BytesIO):
    def write(self, buffer: object, /) -> int:
        # Pillow's PNG writer supplies bytes. Do not accumulate a large encoded
        # result before enforcing the same limit as the original upload.
        if not isinstance(buffer, bytes):
            raise TypeError("Image encoder produced an unsupported buffer")
        if self.tell() + len(buffer) > MAX_MEDIA_BYTES:
            raise MediaNormalizationError("Normalized image exceeds the 5 MiB upload limit")
        return super().write(buffer)


def normalize_image(data: bytes, mime_type: str) -> bytes:
    """Validate one complete static image, orient its pixels, and strip metadata.

    Both the source and normalized representation must fit the byte limit. No
    resizing, frame selection, remote fetching, disk storage, or metadata copying
    is performed. Conversion uses 8-bit RGB/RGBA; embedded color profiles are not
    applied. Keep Pillow's process-wide strict-decoding flags unchanged.
    """
    if not data or len(data) > MAX_MEDIA_BYTES:
        raise MediaNormalizationError("Media image must contain at most 5 MiB")
    image_format = _FORMATS.get(mime_type)
    if image_format is None or not _matches_signature(data, image_format):
        raise MediaNormalizationError("Media bytes do not match the declared MIME type")
    # Other code must not globally opt this security boundary into accepting
    # truncated data. Fail closed without changing shared Pillow configuration.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise MediaNormalizationError("Strict image decoding is unavailable")

    try:
        _validate_container(data, image_format)
        with Image.open(BytesIO(data), formats=[image_format]) as source:
            _validate_image_header(source, image_format)
            source.verify()
        # verify() does not decode pixel data and invalidates some image handles.
        # A fresh open + full load is required, not an optional thumbnail decode.
        with Image.open(BytesIO(data), formats=[image_format]) as source:
            _validate_image_header(source, image_format)
            source.load()
            _validate_image_header(source, image_format)
            with _orient_pixels(source) as oriented:
                mode: Literal["RGB", "RGBA"] = (
                    "RGBA"
                    if "A" in oriented.getbands() or "transparency" in oriented.info
                    else "RGB"
                )
                with oriented.convert(mode) as pixels, Image.new(mode, oriented.size) as clean:
                    # A fresh canvas keeps EXIF/GPS, XMP, ICC, PNG text, comments,
                    # thumbnails, and source encoder settings out of the output.
                    clean.paste(pixels)
                    with _BoundedOutput() as encoded:
                        clean.save(encoded, format="PNG", compress_level=6, optimize=False)
                        return encoded.getvalue()
    except MediaNormalizationError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        TypeError,
        OverflowError,
        IndexError,
        KeyError,
        AttributeError,
        RecursionError,
        SyntaxError,
        EOFError,
        struct.error,
    ):
        # Decoder/metadata exceptions may contain untrusted file content. Do not
        # forward their messages or preserve a verbose exception chain.
        raise MediaNormalizationError(_INVALID_IMAGE) from None


def _orient_pixels(source: Image.Image) -> Image.Image:
    # ImageOps.exif_transpose also rewrites source EXIF/XMP. Only the orientation
    # scalar is needed here; never serialize untrusted metadata just to strip it.
    orientation = source.getexif().get(274, 1)
    if type(orientation) is not int or orientation not in range(1, 9):
        raise MediaNormalizationError("Media image has an invalid EXIF orientation")
    transpose = _ORIENTATION_TRANSPOSES.get(orientation)
    return source.copy() if transpose is None else source.transpose(transpose)


def _matches_signature(data: bytes, image_format: str) -> bool:
    if image_format == "PNG":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if image_format == "JPEG":
        return data.startswith(b"\xff\xd8\xff")
    return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def _validate_image_header(source: Image.Image, expected_format: str) -> None:
    if source.format != expected_format:
        raise MediaNormalizationError("Media bytes do not match the declared MIME type")
    width, height = source.size
    if (
        width < 1
        or height < 1
        or max(width, height) > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise MediaNormalizationError("Media image exceeds the dimension or pixel limit")
    if getattr(source, "n_frames", 1) != 1 or getattr(source, "is_animated", False):
        raise MediaNormalizationError("Animated or multi-frame media images are not supported")


def _validate_container(data: bytes, image_format: str) -> None:
    if image_format == "JPEG":
        _validate_jpeg_framing(data)
        return
    if image_format == "WEBP":
        if int.from_bytes(data[4:8], "little") != len(data) - 8:
            raise MediaNormalizationError(_INVALID_IMAGE)
        offset = 12
        while offset < len(data):
            if len(data) - offset < 8:
                raise MediaNormalizationError(_INVALID_IMAGE)
            kind = data[offset : offset + 4]
            size = int.from_bytes(data[offset + 4 : offset + 8], "little")
            offset += 8 + size + size % 2
            if offset > len(data):
                raise MediaNormalizationError(_INVALID_IMAGE)
            if kind in {b"ANIM", b"ANMF"}:
                raise MediaNormalizationError("Animated media images are not supported")
        return

    offset = 8
    seen_header = False
    seen_palette = False
    seen_pixels = False
    pixels_ended = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise MediaNormalizationError(_INVALID_IMAGE)
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + size
        if end > len(data):
            raise MediaNormalizationError(_INVALID_IMAGE)
        expected_crc = int.from_bytes(data[end - 4 : end], "big")
        if zlib.crc32(data[offset + 4 : end - 4]) != expected_crc:
            raise MediaNormalizationError(_INVALID_IMAGE)
        if any(not (65 <= letter <= 90 or 97 <= letter <= 122) for letter in kind):
            raise MediaNormalizationError(_INVALID_IMAGE)
        if not seen_header and kind != b"IHDR":
            raise MediaNormalizationError(_INVALID_IMAGE)
        if kind == b"IHDR":
            if seen_header or size != 13:
                raise MediaNormalizationError(_INVALID_IMAGE)
            seen_header = True
        elif kind == b"PLTE":
            if seen_palette or seen_pixels:
                raise MediaNormalizationError(_INVALID_IMAGE)
            seen_palette = True
        elif kind == b"IDAT":
            if pixels_ended:
                raise MediaNormalizationError(_INVALID_IMAGE)
            seen_pixels = True
        elif not kind[0] & 32 and kind != b"IEND":
            raise MediaNormalizationError(_INVALID_IMAGE)  # Unknown critical chunk.
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise MediaNormalizationError("Animated media images are not supported")
        if seen_pixels and kind != b"IDAT":
            pixels_ended = True
        if kind == b"IEND":
            if size != 0 or end != len(data) or not seen_pixels:
                raise MediaNormalizationError(_INVALID_IMAGE)
            return
        offset = end
    raise MediaNormalizationError(_INVALID_IMAGE)


def _validate_jpeg_framing(data: bytes) -> None:
    """Bound marker segments and require the first real EOI to end the input.

    This is framing validation, not a replacement for Pillow's entropy decoder.
    Follow T.81 Annex B marker lengths, scan byte stuffing, fill bytes, and restart
    markers; allow multiple scans in progressive JPEG but not multiple frames.
    """
    offset = 2  # The signature check already required SOI.
    in_scan = False
    saw_scan = False
    frame_count = 0
    while offset < len(data):
        if in_scan:
            offset = data.find(b"\xff", offset)
            if offset < 0:
                raise MediaNormalizationError(_INVALID_IMAGE)
        elif data[offset] != 0xFF:
            raise MediaNormalizationError(_INVALID_IMAGE)
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset == len(data):
            raise MediaNormalizationError(_INVALID_IMAGE)
        marker = data[offset]
        offset += 1
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            if not in_scan:
                raise MediaNormalizationError(_INVALID_IMAGE)
            continue  # Stuffed data byte or standalone restart within a scan.
        if marker == 0xD9:
            if not saw_scan or offset != len(data):
                raise MediaNormalizationError(_INVALID_IMAGE)
            return
        if marker == 0x01:
            continue  # Standalone TEM marker; Pillow still validates the coding.
        if marker == 0xD8 or marker < 0xC0 or len(data) - offset < 2:
            raise MediaNormalizationError(_INVALID_IMAGE)
        size = int.from_bytes(data[offset : offset + 2], "big")
        end = offset + size
        if size < 2 or end > len(data):
            raise MediaNormalizationError(_INVALID_IMAGE)
        if marker in _JPEG_FRAME_MARKERS:
            frame_count += 1
            if frame_count > 1:
                raise MediaNormalizationError("Multi-frame media images are not supported")
        if marker == 0xE2 and size >= 6 and data[offset + 2 : offset + 6] == b"MPF\x00":
            raise MediaNormalizationError("Multi-frame media images are not supported")
        if marker == 0xDA:
            saw_scan = True
            in_scan = True
        elif marker != 0xDC:
            in_scan = False  # DNL is the one length-bearing marker within a scan.
        offset = end
    raise MediaNormalizationError(_INVALID_IMAGE)
