"""The ThumbHash placeholder encoder: small, and it decodes back to roughly the same picture."""

import base64

from PIL import Image

from app.services import thumbhash


def _two_tone(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (220, 30, 30) if x < width // 2 else (30, 30, 220))
    return image


def test_hash_is_tiny_and_keeps_the_colours_and_shape(tmp_path) -> None:
    path = tmp_path / "p.png"
    _two_tone(64, 32).save(path)
    encoded = thumbhash.thumbhash_of_image(path)
    raw = base64.b64decode(encoded)
    assert 12 <= len(raw) <= 40

    w, h, rgba = thumbhash.thumbhash_to_rgba(raw)
    assert w > h  # a landscape photo stays landscape
    left = rgba[(h // 2 * w + 2) * 4 : (h // 2 * w + 2) * 4 + 3]
    right = rgba[(h // 2 * w + w - 3) * 4 : (h // 2 * w + w - 3) * 4 + 3]
    assert left[0] > 150 and left[2] < 110  # reddish
    assert right[2] > 150 and right[0] < 110  # bluish


def test_portrait_and_square_shapes(tmp_path) -> None:
    for size, wider in (((32, 64), False), ((50, 50), None)):
        path = tmp_path / f"{size[0]}x{size[1]}.png"
        _two_tone(*size).save(path)
        raw = base64.b64decode(thumbhash.thumbhash_of_image(path))
        w, h, _ = thumbhash.thumbhash_to_rgba(raw)
        if wider is False:
            assert h > w
        else:
            assert abs(w - h) <= 1


def test_transparent_image_has_alpha(tmp_path) -> None:
    path = tmp_path / "t.png"
    Image.new("RGBA", (40, 40), (10, 200, 10, 0)).save(path)
    raw = base64.b64decode(thumbhash.thumbhash_of_image(path))
    assert raw[2] & 0x80  # the has-alpha flag


def test_unreadable_file_gives_none(tmp_path) -> None:
    path = tmp_path / "x.png"
    path.write_bytes(b"not an image")
    assert thumbhash.thumbhash_of_image(path) is None
    assert thumbhash.thumbhash_of_image(tmp_path / "missing.png") is None
