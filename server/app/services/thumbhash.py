"""ThumbHash: a 20-30 byte blurry stand-in for an image (a port of the MIT-licensed reference
implementation by Evan Wallace, https://evanw.github.io/thumbhash/).

A photo grid shows this instantly (decoded to a 32 px bitmap, stretched to the cell) while the real
thumbnail is still on its way, so a screen of photos is never a screen of grey boxes. The encoder
runs on the server when a thumbnail is made; clients only decode.
"""

import base64
import math
from pathlib import Path

MAX_SIDE = 100


def rgba_to_thumbhash(w: int, h: int, rgba: bytes) -> bytes:
    """Encodes `w`x`h` RGBA pixels (at most 100x100) into a ThumbHash."""
    if w > MAX_SIDE or h > MAX_SIDE:
        raise ValueError(f"{w}x{h} does not fit in {MAX_SIDE}x{MAX_SIDE}")
    n = w * h
    avg_r = avg_g = avg_b = avg_a = 0.0
    for i in range(n):
        j = i * 4
        alpha = rgba[j + 3] / 255
        avg_r += alpha / 255 * rgba[j]
        avg_g += alpha / 255 * rgba[j + 1]
        avg_b += alpha / 255 * rgba[j + 2]
        avg_a += alpha
    if avg_a:
        avg_r /= avg_a
        avg_g /= avg_a
        avg_b /= avg_a

    has_alpha = avg_a < n
    l_limit = 5 if has_alpha else 7
    lx = max(1, round(l_limit * w / max(w, h)))
    ly = max(1, round(l_limit * h / max(w, h)))
    lum, p_ch, q_ch, a_ch = [], [], [], []
    for i in range(n):
        j = i * 4
        alpha = rgba[j + 3] / 255
        r = avg_r * (1 - alpha) + alpha / 255 * rgba[j]
        g = avg_g * (1 - alpha) + alpha / 255 * rgba[j + 1]
        b = avg_b * (1 - alpha) + alpha / 255 * rgba[j + 2]
        lum.append((r + g + b) / 3)
        p_ch.append((r + g) / 2 - b)
        q_ch.append(r - g)
        a_ch.append(alpha)

    def encode_channel(channel: list[float], nx: int, ny: int):
        dc = 0.0
        ac: list[float] = []
        scale = 0.0
        for cy in range(ny):
            cx = 0
            while cx * ny < nx * (ny - cy):
                fx = [math.cos(math.pi / w * cx * (x + 0.5)) for x in range(w)]
                f = 0.0
                for y in range(h):
                    fy = math.cos(math.pi / h * cy * (y + 0.5))
                    row = y * w
                    for x in range(w):
                        f += channel[row + x] * fx[x] * fy
                f /= n
                if cx or cy:
                    ac.append(f)
                    scale = max(scale, abs(f))
                else:
                    dc = f
                cx += 1
        if scale:
            ac = [0.5 + 0.5 / scale * value for value in ac]
        return dc, ac, scale

    l_dc, l_ac, l_scale = encode_channel(lum, max(3, lx), max(3, ly))
    p_dc, p_ac, p_scale = encode_channel(p_ch, 3, 3)
    q_dc, q_ac, q_scale = encode_channel(q_ch, 3, 3)
    if has_alpha:
        a_dc, a_ac, a_scale = encode_channel(a_ch, 5, 5)

    is_landscape = w > h
    header24 = (
        round(63 * l_dc)
        | (round(31.5 + 31.5 * p_dc) << 6)
        | (round(31.5 + 31.5 * q_dc) << 12)
        | (round(31 * l_scale) << 18)
        | (int(has_alpha) << 23)
    )
    header16 = (
        (ly if is_landscape else lx)
        | (round(63 * p_scale) << 3)
        | (round(63 * q_scale) << 9)
        | (int(is_landscape) << 15)
    )
    out = [header24 & 255, (header24 >> 8) & 255, header24 >> 16, header16 & 255, header16 >> 8]
    ac_start = 6 if has_alpha else 5
    if has_alpha:
        out.append(round(15 * a_dc) | (round(15 * a_scale) << 4))
    channels = [l_ac, p_ac, q_ac, a_ac] if has_alpha else [l_ac, p_ac, q_ac]
    index = 0
    for ac in channels:
        for f in ac:
            slot = ac_start + (index >> 1)
            while len(out) <= slot:
                out.append(0)
            out[slot] |= round(15 * f) << ((index & 1) << 2)
            index += 1
    return bytes(out)


def aspect_ratio(hash_bytes: bytes) -> float:
    has_alpha = hash_bytes[2] & 0x80
    l_max = 5 if has_alpha else 7
    l_min = hash_bytes[3] & 7
    is_landscape = hash_bytes[4] & 0x80
    lx = l_max if is_landscape else l_min
    ly = l_min if is_landscape else l_max
    return lx / ly


def thumbhash_to_rgba(hash_bytes: bytes) -> tuple[int, int, bytes]:
    """Decodes to (width, height, RGBA), at most 32 px on the long side. Used by tests."""
    header24 = hash_bytes[0] | (hash_bytes[1] << 8) | (hash_bytes[2] << 16)
    header16 = hash_bytes[3] | (hash_bytes[4] << 8)
    l_dc = (header24 & 63) / 63
    p_dc = ((header24 >> 6) & 63) / 31.5 - 1
    q_dc = ((header24 >> 12) & 63) / 31.5 - 1
    l_scale = ((header24 >> 18) & 31) / 31
    has_alpha = header24 >> 23
    p_scale = ((header16 >> 3) & 63) / 63
    q_scale = ((header16 >> 9) & 63) / 63
    is_landscape = header16 >> 15
    lx = max(3, (7 if not has_alpha else 5) if is_landscape else header16 & 7)
    ly = max(3, header16 & 7 if is_landscape else (5 if has_alpha else 7))
    a_dc = (hash_bytes[5] & 15) / 15 if has_alpha else 1.0
    a_scale = (hash_bytes[5] >> 4) / 15 if has_alpha else 0.0

    ac_start = 6 if has_alpha else 5
    state = {"i": 0}

    def decode_channel(nx: int, ny: int, scale: float) -> list[float]:
        ac = []
        for cy in range(ny):
            cx = 0 if cy else 1
            while cx * ny < nx * (ny - cy):
                byte = hash_bytes[ac_start + (state["i"] >> 1)]
                ac.append((((byte >> ((state["i"] & 1) << 2)) & 15) / 7.5 - 1) * scale)
                state["i"] += 1
                cx += 1
        return ac

    l_ac = decode_channel(lx, ly, l_scale)
    p_ac = decode_channel(3, 3, p_scale * 1.25)
    q_ac = decode_channel(3, 3, q_scale * 1.25)
    a_ac = decode_channel(5, 5, a_scale) if has_alpha else []

    ratio = aspect_ratio(hash_bytes)
    w = round(32 if ratio > 1 else 32 * ratio)
    h = round(32 / ratio if ratio > 1 else 32)
    rgba = bytearray(w * h * 4)
    i = 0
    for y in range(h):
        for x in range(w):
            lum, p, q, a = l_dc, p_dc, q_dc, a_dc
            nxs = max(lx, 5 if has_alpha else 3)
            nys = max(ly, 5 if has_alpha else 3)
            fx = [math.cos(math.pi / w * (x + 0.5) * cx) for cx in range(nxs)]
            fy = [math.cos(math.pi / h * (y + 0.5) * cy) for cy in range(nys)]
            j = 0
            for cy in range(ly):
                cx = 0 if cy else 1
                fy2 = fy[cy] * 2
                while cx * ly < lx * (ly - cy):
                    lum += l_ac[j] * fx[cx] * fy2
                    cx += 1
                    j += 1
            j = 0
            for cy in range(3):
                cx = 0 if cy else 1
                fy2 = fy[cy] * 2
                while cx < 3 - cy:
                    f = fx[cx] * fy2
                    p += p_ac[j] * f
                    q += q_ac[j] * f
                    cx += 1
                    j += 1
            if has_alpha:
                j = 0
                for cy in range(5):
                    cx = 0 if cy else 1
                    fy2 = fy[cy] * 2
                    while cx < 5 - cy:
                        a += a_ac[j] * fx[cx] * fy2
                        cx += 1
                        j += 1
            b = lum - 2 / 3 * p
            r = (3 * lum - b + q) / 2
            g = r - q
            rgba[i] = max(0, min(255, round(255 * r)))
            rgba[i + 1] = max(0, min(255, round(255 * g)))
            rgba[i + 2] = max(0, min(255, round(255 * b)))
            rgba[i + 3] = max(0, min(255, round(255 * a)))
            i += 4
    return w, h, bytes(rgba)


def thumbhash_of_image(path: Path) -> str | None:
    """Base64 ThumbHash of an image file (any size; it is shrunk to 32 px first), or None."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGBA")
            image.thumbnail((32, 32))
            w, h = image.size
            return base64.b64encode(rgba_to_thumbhash(w, h, image.tobytes())).decode("ascii")
    except Exception:
        return None
