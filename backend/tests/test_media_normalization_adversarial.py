from __future__ import annotations

import struct
from io import BytesIO

import pytest
from PIL import Image

from job_apply_pro.ai.media_normalization import MediaNormalizationError, normalize_image


def _jpeg(*, progressive: bool = False, restart_marker_blocks: int = 0) -> bytes:
    pixels = bytes((index * 37 + index // 11) % 256 for index in range(32 * 24 * 3))
    with Image.frombytes("RGB", (32, 24), pixels) as image, BytesIO() as output:
        image.save(
            output,
            format="JPEG",
            quality=90,
            progressive=progressive,
            restart_marker_blocks=restart_marker_blocks,
        )
        return output.getvalue()


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def test_orientation_does_not_reserialize_malformed_unrelated_exif() -> None:
    # Orientation is valid, but ImageDescription has RATIONAL instead of ASCII.
    # Pillow can read these pixels. Its metadata-rewriting exif_transpose helper
    # used to raise AttributeError while reserializing the unrelated description.
    tiff = (
        b"II"
        + struct.pack("<HI", 42, 8)
        + struct.pack("<H", 2)
        + struct.pack("<HHII", 274, 3, 1, 6)
        + struct.pack("<HHII", 270, 5, 1, 0)
        + struct.pack("<I", 0)
        + b"\x00" * 64
    )
    original = _jpeg()
    source = original[:2] + _segment(0xE1, b"Exif\x00\x00" + tiff) + original[2:]

    normalized = normalize_image(source, "image/jpeg")

    with Image.open(BytesIO(normalized)) as image:
        image.load()
        assert image.size == (24, 32)
        assert image.format == "PNG"
        assert not image.getexif() and not image.info


@pytest.mark.parametrize(
    ("tag_type", "count", "value"),
    [(3, 1, 0), (3, 1, 9), (3, 1, 65_535), (2, 2, ord("6"))],
)
def test_invalid_exif_orientation_is_rejected_without_reflecting_metadata(
    tag_type: int, count: int, value: int
) -> None:
    tiff = (
        b"II"
        + struct.pack("<HI", 42, 8)
        + struct.pack("<H", 1)
        + struct.pack("<HHII", 274, tag_type, count, value)
        + struct.pack("<I", 0)
    )
    original = _jpeg()
    source = original[:2] + _segment(0xE1, b"Exif\x00\x00" + tiff) + original[2:]
    with pytest.raises(MediaNormalizationError, match="orientation"):
        normalize_image(source, "image/jpeg")


def test_only_pillow_parsed_orientation_is_used_after_metadata_warning() -> None:
    # Pillow warns and chooses the first item for this duplicated SHORT value.
    # The contract validates that parsed scalar, not every raw EXIF tag encoding.
    tiff = (
        b"II"
        + struct.pack("<HI", 42, 8)
        + struct.pack("<H", 1)
        + struct.pack("<HHII", 274, 3, 2, 6 + (6 << 16))
        + struct.pack("<I", 0)
    )
    original = _jpeg()
    source = original[:2] + _segment(0xE1, b"Exif\x00\x00" + tiff) + original[2:]
    with pytest.warns(UserWarning, match="tag 274 had too many entries"):
        normalized = normalize_image(source, "image/jpeg")
    with Image.open(BytesIO(normalized)) as image:
        assert image.size == (24, 32)
        assert not image.getexif() and not image.info


@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("tail", [b"synthetic-extra-data\xff\xd9", b"\xff\xd9"])
def test_jpeg_rejects_bytes_after_first_end_of_image(progressive: bool, tail: bytes) -> None:
    with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
        normalize_image(_jpeg(progressive=progressive) + tail, "image/jpeg")


def test_concatenated_jpegs_are_not_a_single_static_image() -> None:
    with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
        normalize_image(_jpeg() + _jpeg(progressive=True), "image/jpeg")


@pytest.mark.parametrize("segment_length", [0, 1, 65_535])
def test_jpeg_rejects_invalid_or_truncated_segment_length(segment_length: int) -> None:
    original = _jpeg()
    source = original[:2] + b"\xff\xe1" + struct.pack(">H", segment_length) + original[2:]
    with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
        normalize_image(source, "image/jpeg")


@pytest.mark.parametrize("progressive", [False, True])
def test_jpeg_markers_embedded_inside_metadata_are_not_frame_delimiters(progressive: bool) -> None:
    original = _jpeg(progressive=progressive)
    comment = b"synthetic-comment\xff\xd9\xff\xd8\xff\xda\x00\x00"
    source = original[:2] + _segment(0xFE, comment) + original[2:]

    assert normalize_image(source, "image/jpeg") == normalize_image(original, "image/jpeg")


@pytest.mark.parametrize("progressive", [False, True])
def test_baseline_and_progressive_jpeg_decode_without_lossy_revalidation(progressive: bool) -> None:
    normalized = normalize_image(_jpeg(progressive=progressive), "image/jpeg")
    assert normalize_image(normalized, "image/png") == normalized
    with Image.open(BytesIO(normalized)) as image:
        image.load()
        assert image.size == (32, 24)
        assert not image.info


@pytest.mark.parametrize("progressive", [False, True])
def test_jpeg_generated_restart_markers_preserve_decoded_pixels(progressive: bool) -> None:
    source = _jpeg(progressive=progressive, restart_marker_blocks=1)
    assert any(bytes([0xFF, marker]) in source for marker in range(0xD0, 0xD8))
    assert normalize_image(source, "image/jpeg") == normalize_image(
        _jpeg(progressive=progressive), "image/jpeg"
    )


@pytest.mark.parametrize("progressive", [False, True])
def test_jpeg_accepts_marker_fill_bytes_between_header_segments(progressive: bool) -> None:
    original = _jpeg(progressive=progressive)
    source = original[:2] + b"\xff\xff" + original[2:]
    assert normalize_image(source, "image/jpeg") == normalize_image(original, "image/jpeg")
