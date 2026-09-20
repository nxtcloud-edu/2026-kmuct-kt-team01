from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image, ImageCms

from backend.app.edits import EditError, EditSettings, render_edit


def image_file(mode="RGB", color=(100, 60, 20), size=(8, 6), fmt="PNG", **kwargs):
    stream = BytesIO()
    with Image.new(mode, size, color) as image:
        image.save(stream, format=fmt, **kwargs)
    stream.seek(0)
    return stream


def rendered(source, brightness=1.0, saturation=1.0, **kwargs):
    destination = BytesIO()
    result = render_edit(source, destination, EditSettings(brightness, saturation), **kwargs)
    destination.seek(0)
    return result, Image.open(destination)


def test_brightness_and_desaturation_preserve_original():
    original = image_file()
    before = sha256(original.getvalue()).hexdigest()
    result, output = rendered(original, 0.5, 0)
    with output:
        assert output.format == "JPEG"
        assert output.size == (8, 6)
        # Pillow luma of (50, 30, 10) is 34; JPEG allows rounding of 1.
        assert all(abs(channel - 34) <= 1 for channel in output.getpixel((0, 0)))
    assert sha256(original.getvalue()).hexdigest() == before
    assert result.original_sha256 == before
    assert result.byte_size > 0


def test_exif_orientation_applied_and_not_carried_into_output():
    exif = Image.Exif()
    exif[274] = 6
    _, output = rendered(image_file(size=(10, 4), fmt="JPEG", exif=exif))
    with output:
        assert output.size == (4, 10)
        assert output.getexif().get(274) is None


@pytest.mark.parametrize("mode,color", [("RGBA", (255, 0, 0, 0)), ("LA", (0, 0))])
def test_transparency_is_composited_on_white(mode, color):
    _, output = rendered(image_file(mode, color))
    with output:
        assert output.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("brightness,saturation", [(0.49, 1), (1.51, 1), (1, -0.1), (1, 2.1), (float("nan"), 1), (1, float("inf")), (True, 1)])
def test_invalid_settings_are_rejected(brightness, saturation):
    with pytest.raises(EditError) as error:
        EditSettings(brightness, saturation)
    assert error.value.code == "INVALID_EDIT_SETTINGS"


@pytest.mark.parametrize("payload,code", [(b"not an image", "INVALID_IMAGE"), (image_file(fmt="GIF").getvalue(), "UNSUPPORTED_IMAGE")])
def test_invalid_or_disallowed_formats_rejected(payload, code):
    with pytest.raises(EditError) as error:
        rendered(BytesIO(payload))
    assert error.value.code == code


def test_byte_and_pixel_limits_checked_before_decode():
    for limits, code in [({"max_bytes": 4}, "IMAGE_TOO_LARGE"), ({"max_pixels": 20}, "TOO_MANY_PIXELS")]:
        with pytest.raises(EditError) as error:
            rendered(image_file(), **limits)
        assert error.value.code == code


def test_truncated_png_is_rejected():
    data = image_file(size=(100, 100)).getvalue()
    with pytest.raises(EditError) as error:
        rendered(BytesIO(data[:len(data) // 2]))
    assert error.value.code == "INVALID_IMAGE"


def test_repeated_render_is_deterministic_and_reports_output_hash():
    outputs = []
    for _ in range(2):
        target = BytesIO()
        result = render_edit(image_file(), target, EditSettings(1.2, 0.7))
        assert result.sha256 == sha256(target.getvalue()).hexdigest()
        outputs.append(target.getvalue())
    assert outputs[0] == outputs[1]


def test_embedded_cmyk_profile_is_applied_to_native_channels(monkeypatch):
    # Isolate the external ICC transform, not decoding/rendering. Native mode is
    # essential: passing RGB pixels with a CMYK profile breaks real LittleCMS.
    # Also manually verified against Windows RSWOP.icm; that profile is not distributed.
    monkeypatch.setattr(ImageCms, "ImageCmsProfile", lambda value: value)

    def transform(image, input_profile, output_profile, *, outputMode):
        assert image.mode == "CMYK"
        assert outputMode == "RGB"
        return Image.new("RGB", image.size, (223, 170, 128))

    monkeypatch.setattr(ImageCms, "profileToProfile", transform)
    _, output = rendered(image_file("CMYK", (20, 80, 120, 10), fmt="JPEG", icc_profile=b"fixture-profile"))
    with output:
        assert all(abs(a - b) <= 2 for a, b in zip(output.getpixel((0, 0)), (223, 170, 128)))


def test_srgb_profile_preserves_transparency_and_color():
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    _, output = rendered(image_file("RGBA", (20, 80, 120, 0), icc_profile=profile))
    with output:
        assert output.getpixel((0, 0)) == (255, 255, 255)
