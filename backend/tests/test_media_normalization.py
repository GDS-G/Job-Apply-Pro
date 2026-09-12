from __future__ import annotations

import random
import zlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Literal

import pytest
from PIL import Image, ImageFile
from PIL.PngImagePlugin import PngInfo

from image_helpers import synthetic_image_bytes
from job_apply_pro.ai import media_normalization
from job_apply_pro.ai.media_normalization import MediaNormalizationError, normalize_image
from job_apply_pro.domain import ai as ai_domain
from job_apply_pro.domain.ai import AIGatewayRequest, AIInputPart, AIProviderRequest, AITaskType

ImageFormat = Literal["JPEG", "PNG", "WEBP"]


def _mime(image_format: ImageFormat) -> str:
    return f"image/{image_format.lower()}"


def _encode(source: Image.Image, image_format: str = "PNG", **options: object) -> bytes:
    with BytesIO() as output:
        source.save(output, format=image_format, **options)
        return output.getvalue()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        len(payload).to_bytes(4, "big")
        + kind
        + payload
        + zlib.crc32(kind + payload).to_bytes(4, "big")
    )


def _replace_png_chunk(data: bytes, kind: bytes, payload: bytes) -> bytes:
    offset = 8
    while offset < len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        end = offset + size + 12
        if data[offset + 4 : offset + 8] == kind:
            return data[:offset] + _png_chunk(kind, payload) + data[end:]
        offset = end
    raise AssertionError("Synthetic image does not contain requested PNG chunk")


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_all_approved_formats_decode_to_metadata_free_png(image_format: ImageFormat) -> None:
    data = synthetic_image_bytes(image_format, metadata="synthetic-private-metadata")
    normalized = normalize_image(data, _mime(image_format))
    assert b"synthetic-private-metadata" not in normalized
    with Image.open(BytesIO(data)) as original, Image.open(BytesIO(normalized)) as result:
        assert result.format == "PNG"
        assert result.mode == "RGB"
        assert result.info == {}
        assert dict(result.getexif()) == {}
        assert result.size == original.size
        assert result.tobytes() == original.convert("RGB").tobytes()
    assert normalize_image(normalized, "image/png") == normalized


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_metadata_only_changes_do_not_change_normalized_bytes(image_format: ImageFormat) -> None:
    left = synthetic_image_bytes(image_format, metadata="synthetic-first-private-note")
    right = synthetic_image_bytes(image_format, metadata="synthetic-second-private-note")
    assert left != right
    assert normalize_image(left, _mime(image_format)) == normalize_image(right, _mime(image_format))


def test_normalization_uses_clean_canvas_and_only_required_png_chunks() -> None:
    exif = Image.Exif()
    exif[270] = "synthetic-description"
    exif[315] = "synthetic-author"
    info = PngInfo()
    info.add_text("Comment", "synthetic-comment")
    info.add_itxt("XML:com.adobe.xmp", "synthetic-xmp")
    with Image.new("RGB", (4, 3), (10, 20, 30)) as source:
        encoded = _encode(
            source,
            pnginfo=info,
            exif=exif,
            icc_profile=b"synthetic-icc-profile",
            dpi=(300, 300),
        )
    normalized = normalize_image(encoded, "image/png")
    assert b"synthetic" not in normalized
    kinds = []
    offset = 8
    while offset < len(normalized):
        kinds.append(normalized[offset + 4 : offset + 8])
        offset += int.from_bytes(normalized[offset : offset + 4], "big") + 12
    assert kinds == [b"IHDR", b"IDAT", b"IEND"]


@pytest.mark.parametrize(
    ("orientation", "transpose"),
    [
        (2, Image.Transpose.FLIP_LEFT_RIGHT),
        (3, Image.Transpose.ROTATE_180),
        (4, Image.Transpose.FLIP_TOP_BOTTOM),
        (5, Image.Transpose.TRANSPOSE),
        (6, Image.Transpose.ROTATE_270),
        (7, Image.Transpose.TRANSVERSE),
        (8, Image.Transpose.ROTATE_90),
    ],
)
def test_exif_orientation_is_applied_then_removed(
    orientation: int, transpose: Image.Transpose
) -> None:
    exif = Image.Exif()
    exif[274] = orientation
    exif[270] = "synthetic-private-description"
    with Image.frombytes("RGB", (2, 3), bytes(range(18))) as source:
        encoded = _encode(source, exif=exif)
        with source.transpose(transpose) as expected:
            normalized = normalize_image(encoded, "image/png")
            with Image.open(BytesIO(normalized)) as result:
                assert result.size == expected.size
                assert result.tobytes() == expected.tobytes()
                assert dict(result.getexif()) == {}


def test_alpha_and_palette_transparency_are_preserved() -> None:
    with Image.new("RGBA", (3, 2), (12, 34, 56, 78)) as source:
        normalized = normalize_image(_encode(source), "image/png")
        with Image.open(BytesIO(normalized)) as result:
            assert result.mode == "RGBA"
            assert result.tobytes() == source.tobytes()
    with Image.new("P", (3, 2), 0) as source:
        source.putpalette([12, 34, 56] + [0] * 765)
        encoded = _encode(source, transparency=0)
        with Image.open(BytesIO(normalize_image(encoded, "image/png"))) as result:
            assert result.mode == "RGBA"
            assert result.getpixel((0, 0)) == (12, 34, 56, 0)


@pytest.mark.parametrize(
    ("data", "mime_type"),
    [
        (b"\x89PNG\r\n\x1a\nfixture", "image/png"),
        (b"\xff\xd8\xfffixture\xff\xd9", "image/jpeg"),
        (b"RIFF\x04\x00\x00\x00WEBP", "image/webp"),
    ],
)
def test_magic_bytes_alone_are_not_an_image(data: bytes, mime_type: str) -> None:
    with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
        normalize_image(data, mime_type)


def test_declared_mime_is_checked_before_normalization() -> None:
    with pytest.raises(MediaNormalizationError, match="do not match"):
        normalize_image(synthetic_image_bytes("JPEG"), "image/png")
    with pytest.raises(MediaNormalizationError, match="do not match"):
        normalize_image(synthetic_image_bytes("PNG"), "image/gif")


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_truncated_complete_images_are_rejected(image_format: ImageFormat) -> None:
    with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
        normalize_image(synthetic_image_bytes(image_format)[:-1], _mime(image_format))


def test_png_crc_including_iend_and_compressed_payload_are_verified() -> None:
    encoded = synthetic_image_bytes()
    bad_iend_crc = encoded[:-1] + bytes([encoded[-1] ^ 1])
    corrupt_idat = _replace_png_chunk(encoded, b"IDAT", b"synthetic-invalid-zlib-data")
    for corrupt in (bad_iend_crc, corrupt_idat, encoded + b"synthetic-trailing-content"):
        with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
            normalize_image(corrupt, "image/png")


def test_png_rejects_duplicate_headers_unknown_critical_chunks_and_disjoint_pixels() -> None:
    encoded = synthetic_image_bytes()
    second_header = _png_chunk(b"IHDR", encoded[16:29])
    unknown_critical = _png_chunk(b"ABCD", b"synthetic")
    split_pixels = _png_chunk(b"tEXt", b"Comment\x00synthetic") + _png_chunk(b"IDAT", b"")
    for inserted in (second_header, unknown_critical, split_pixels):
        malformed = encoded[:-12] + inserted + encoded[-12:]
        with pytest.raises(MediaNormalizationError, match="corrupt or incomplete"):
            normalize_image(malformed, "image/png")


@pytest.mark.parametrize("image_format", ["PNG", "WEBP", "MPO"])
def test_multi_frame_images_are_rejected(image_format: str) -> None:
    with Image.new("RGB", (3, 2), "red") as first, Image.new("RGB", (3, 2), "blue") as second:
        data = _encode(first, image_format, save_all=True, append_images=[second], duration=100)
    mime_type = "image/jpeg" if image_format == "MPO" else f"image/{image_format.lower()}"
    with pytest.raises(MediaNormalizationError):
        normalize_image(data, mime_type)


@pytest.mark.parametrize(("width", "height"), [(8_193, 1), (4_096, 4_097)])
def test_dimension_and_pixel_limits_reject_before_full_pixel_decode(
    width: int, height: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = synthetic_image_bytes()
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + original[24:29]
    encoded = _replace_png_chunk(original, b"IHDR", header)

    def unexpected_load(_source: Image.Image) -> None:
        pytest.fail("Oversized image reached pixel allocation")

    monkeypatch.setattr(ImageFile.ImageFile, "load", unexpected_load)
    with pytest.raises(MediaNormalizationError, match="dimension or pixel limit"):
        normalize_image(encoded, "image/png")


def test_source_size_and_configured_resource_limits() -> None:
    assert media_normalization.MAX_MEDIA_BYTES == 5_242_880
    assert media_normalization.MAX_IMAGE_DIMENSION == 8_192
    assert media_normalization.MAX_IMAGE_PIXELS == 16_777_216
    for data in (b"", b"x" * (media_normalization.MAX_MEDIA_BYTES + 1)):
        with pytest.raises(MediaNormalizationError, match="at most 5 MiB"):
            normalize_image(data, "image/png")


def test_lossless_png_expansion_is_bounded_without_resizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A JPEG fits the input bound while its lossless normalized pixels do not.
    with Image.frombytes("RGB", (64, 64), random.Random(82).randbytes(64 * 64 * 3)) as source:
        encoded = _encode(source, "JPEG", quality=30)
    monkeypatch.setattr(media_normalization, "MAX_MEDIA_BYTES", len(encoded) + 10)
    with pytest.raises(MediaNormalizationError, match="Normalized image exceeds"):
        normalize_image(encoded, "image/jpeg")


def test_strict_decoding_global_flags_are_never_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    pixel_limit = Image.MAX_IMAGE_PIXELS
    normalize_image(synthetic_image_bytes(), "image/png")
    assert pixel_limit == Image.MAX_IMAGE_PIXELS
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    with pytest.raises(MediaNormalizationError, match="Strict image decoding is unavailable"):
        normalize_image(synthetic_image_bytes(), "image/png")
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True
    assert pixel_limit == Image.MAX_IMAGE_PIXELS


@pytest.mark.parametrize(
    "error_type", [OSError, TypeError, OverflowError, KeyError, RecursionError]
)
def test_decoder_and_metadata_errors_are_sanitized(
    error_type: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_metadata(_source: Image.Image) -> Image.Image:
        raise error_type("synthetic-private-decoder-content")

    monkeypatch.setattr(media_normalization, "_orient_pixels", fail_metadata)
    with pytest.raises(MediaNormalizationError) as failure:
        normalize_image(synthetic_image_bytes(), "image/png")
    assert str(failure.value) == "Media image is corrupt or incomplete"
    assert failure.value.__suppress_context__ is True


def test_input_parts_remain_byte_stable_through_nesting_and_json_round_trips() -> None:
    part = AIInputPart(kind="media", data=synthetic_image_bytes("JPEG"), mime_type="image/jpeg")
    canonical = part.data
    assert part.mime_type == "image/png"
    gateway = AIGatewayRequest(
        task_type=AITaskType.ANSWER,
        prompt_id="synthetic.answer",
        input_data={},
        input_parts=[part],
        media_upload_consent=True,
    )
    provider = AIProviderRequest(
        model="synthetic-model",
        system_instruction="synthetic",
        user_content="synthetic",
        input_parts=gateway.input_parts,
        timeout_seconds=30,
        media_upload_consent=True,
    )
    reloaded = AIGatewayRequest.model_validate_json(gateway.model_dump_json())
    assert provider.input_parts[0].data == canonical
    assert reloaded.input_parts[0].data == canonical
    assert reloaded.input_parts[0].mime_type == "image/png"


def test_parallel_normalization_is_deterministic() -> None:
    encoded = synthetic_image_bytes("WEBP", metadata="synthetic-private-metadata", orientation=6)
    with ThreadPoolExecutor(max_workers=4) as workers:
        normalized = list(
            workers.map(lambda _index: normalize_image(encoded, "image/webp"), range(8))
        )
    assert len(set(normalized)) == 1


@pytest.mark.parametrize(("count", "consent"), [(5, True), (1, False), (1, None)])
def test_gateway_rejects_excess_media_or_obvious_missing_consent_before_decoding(
    count: int, consent: bool | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_decode(_data: bytes, _mime_type: str) -> bytes:
        pytest.fail("A preflight-rejected request reached image decoding")

    monkeypatch.setattr(ai_domain, "normalize_image", unexpected_decode)
    payload: dict[str, object] = {
        "task_type": "ANSWER",
        "prompt_id": "synthetic.answer",
        "input_data": {},
        "input_parts": [
            {"kind": "media", "data": b"synthetic-invalid", "mime_type": "image/png"}
            for _index in range(count)
        ],
    }
    if consent is not None:
        payload["media_upload_consent"] = consent
    expected = "At most four" if count > 4 else "explicit media-upload consent"
    with pytest.raises(ValueError, match=expected):
        AIGatewayRequest.model_validate(payload)


@pytest.mark.parametrize("consent", [True, "true", "yes", 1])
def test_media_preflight_preserves_pydantic_true_coercion(consent: object) -> None:
    payload = {
        "task_type": "ANSWER",
        "prompt_id": "synthetic.answer",
        "input_data": {},
        "input_parts": [
            {"kind": "media", "data": synthetic_image_bytes(), "mime_type": "image/png"}
        ],
        "media_upload_consent": consent,
    }
    parsed = AIGatewayRequest.model_validate(payload)
    assert parsed.media_upload_consent is True
    assert parsed.input_parts[0].mime_type == "image/png"
