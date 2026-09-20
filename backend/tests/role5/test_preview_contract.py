"""Characterize a known integration gap, not a claim that previews match."""
from backend.tests.role5.test_render import image_file, rendered


def test_css_saturate_zero_and_pillow_color_zero_are_not_equivalent():
    # W3C saturate(0) uses 0.213R + 0.715G + 0.072B in sRGB.
    # Pillow uses approximately 0.299R + 0.587G + 0.114B.
    # A global saturation factor cannot correct red and green simultaneously.
    for color, css_gray, pillow_gray in [((255, 0, 0), 54, 76), ((0, 255, 0), 182, 150)]:
        _, image = rendered(image_file(color=color), 1, 0)
        with image:
            actual = image.getpixel((0, 0))[0]
        assert abs(actual - pillow_gray) <= 1
        assert abs(actual - css_gray) >= 20
