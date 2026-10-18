#!/usr/bin/env python3
"""Builds every logo, icon and favicon from the brand sheet (`choud-brand-assets/brand-sheet.png`).

The sheet is the source of truth for how Choud looks: the dithered cloud with the folder, the pixel
"Choud" wordmark, the rounded app icons and the retro loading screen. This script does not redraw
anything. It cuts the art out of the sheet, turns it into a clean one-colour mask (so one file serves
every theme: the apps tint it), sharpens the pixel edges after enlarging, and writes the sizes each
platform needs.

    python scripts/brand/from_sheet.py            # regenerate everything
    python scripts/brand/from_sheet.py --check    # fail if the committed assets are stale

Needs Python 3.9+ and Pillow (`pip install pillow`).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "choud-brand-assets" / "brand-sheet.png"
WEB_PUBLIC = ROOT / "web" / "public"
WEB_BRAND = ROOT / "web" / "src" / "assets" / "brand"
RES = ROOT / "android" / "app" / "src" / "main" / "res"
NODPI = RES / "drawable-nodpi"

# Where each piece sits on the 1536 x 1024 sheet (measured from the supplied image).
MAIN_DARK = (550, 18, 1024, 450)  # white art on black: the best source for a mask
ENLARGE = 3  # the art is ~430 px wide on the sheet; enlarge, then re-sharpen the edges


# ---------------------------------------------------------------------------------------- masks


def smooth(lum: Image.Image, low: int = 88, high: int = 168) -> Image.Image:
    """Turns a soft grey-scale picture into a crisp mask: below `low` nothing, above `high` solid."""
    table = [0 if v <= low else 255 if v >= high else round(255 * (v - low) / (high - low)) for v in range(256)]
    return lum.point(table)


def art_mask(sheet: Image.Image) -> Image.Image:
    """The whole logo (cloud, folder, wordmark, underline) as an L mask, enlarged and sharp."""
    crop = sheet.crop(MAIN_DARK).convert("L")
    big = crop.resize((crop.width * ENLARGE, crop.height * ENLARGE), Image.LANCZOS)
    return smooth(big)


def tight(mask: Image.Image, pad: int = 0) -> Image.Image:
    box = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
    assert box, "the logo was not found on the sheet"
    left, top, right, bottom = box
    return mask.crop((max(0, left - pad), max(0, top - pad), right + pad, bottom + pad))


def split_cloud_and_wordmark(full: Image.Image) -> tuple[Image.Image, Image.Image]:
    """The cloud (with its folder) on top, the wordmark and its underline below, cut at the empty band."""
    width, height = full.size
    rows = [sum(1 for x in range(0, width, 3) if full.getpixel((x, y)) > 40) for y in range(height)]
    # The widest blank band in the lower 60% is the gap between the cloud and the wordmark.
    best, start = (0, height // 2), None
    for y in range(int(height * 0.4), height):
        if rows[y] == 0:
            start = y if start is None else start
        elif start is not None:
            if y - start > best[0]:
                best = (y - start, start)
            start = None
    cut = best[1] + best[0] // 2
    return tight(full.crop((0, 0, width, cut))), tight(full.crop((0, cut, width, height)))


def painted(mask: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    layer = Image.new("RGBA", mask.size, color + (0,))
    layer.putalpha(mask)
    return layer


def fit(mask: Image.Image, width: int) -> Image.Image:
    height = round(mask.height * width / mask.width)
    return smooth(mask.resize((width, height), Image.LANCZOS), 72, 184)


def on_square(mask: Image.Image, size: int, *, scale: float, color: tuple[int, int, int], dy: float = 0.0) -> Image.Image:
    """The mark centred on a transparent square canvas, `scale` of the canvas wide."""
    mark = fit(mask, round(size * scale))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer = painted(mark, color)
    canvas.alpha_composite(layer, ((size - mark.width) // 2, round((size - mark.height) / 2 + dy * size)))
    return canvas


def rounded_tile(size: int, *, dark: bool, mark: Image.Image) -> Image.Image:
    """The app icon: a rounded square with the mark on it (black with white art, or the reverse)."""
    radius = round(size * 0.22)
    background, ink = ((0, 0, 0), (255, 255, 255)) if dark else ((255, 255, 255), (0, 0, 0))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=background + (255,))
    if not dark:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, outline=(0, 0, 0, 255), width=max(1, size // 128))
    tile.alpha_composite(on_square(mark, size, scale=0.74, color=ink, dy=0.02))
    return tile


# ---------------------------------------------------------------------------------------- outputs


def build(sheet: Image.Image) -> dict[Path, Image.Image]:
    full = tight(art_mask(sheet))
    mark, wordmark = split_cloud_and_wordmark(art_mask(sheet))
    white, black = (255, 255, 255), (0, 0, 0)
    out: dict[Path, Image.Image] = {}

    # --- Android: white masks the app tints to the theme's ink colour
    out[NODPI / "choud_logo_full.png"] = painted(fit(full, 720), white)
    out[NODPI / "choud_wordmark.png"] = painted(fit(wordmark, 600), white)
    out[NODPI / "ic_choud_mark.png"] = painted(fit(mark, 640), white)
    out[NODPI / "ic_choud_foreground.png"] = on_square(mark, 432, scale=0.56, color=white, dy=-0.01)
    out[NODPI / "ic_choud_monochrome.png"] = on_square(mark, 432, scale=0.56, color=black, dy=-0.01)
    out[RES / "drawable-xxxhdpi" / "ic_stat_choud.png"] = on_square(mark, 96, scale=0.92, color=white)

    # --- Web: coloured art on transparent, one for light surfaces and one for dark
    for name, color in (("dark", white), ("light", black)):
        out[WEB_BRAND / f"choud-logo-{name}.png"] = painted(fit(full, 720), color)
        out[WEB_BRAND / f"choud-mark-{name}.png"] = painted(fit(mark, 480), color)
        out[WEB_BRAND / f"choud-icon-{name}.png"] = rounded_tile(256, dark=(name == "dark"), mark=mark)

    # --- Web: installed-app icons and favicons (the dark tile, the way the sheet shows the primary icon)
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")):
        tile = rounded_tile(size, dark=True, mark=mark)
        if name == "apple-touch-icon.png":  # iOS rounds the corners itself and wants no transparency
            flat = Image.new("RGBA", (size, size), (0, 0, 0, 255))
            flat.alpha_composite(on_square(mark, size, scale=0.74, color=white, dy=0.02))
            tile = flat
        out[WEB_PUBLIC / name] = tile
    for size in (16, 32):
        out[WEB_PUBLIC / f"favicon-{size}.png"] = rounded_tile(size * 4, dark=True, mark=mark).resize((size, size), Image.LANCZOS)
    return out


def digest(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes() + str(image.size).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the committed assets differ")
    args = parser.parse_args()
    if not SHEET.exists():
        print(f"missing {SHEET.relative_to(ROOT)}", file=sys.stderr)
        return 1
    produced = build(Image.open(SHEET).convert("RGBA"))
    if args.check:
        stale = [p for p, img in produced.items() if not p.exists() or digest(Image.open(p).convert("RGBA")) != digest(img)]
        if stale:
            print("stale brand assets (run scripts/brand/from_sheet.py):")
            for path in stale:
                print("  ", path.relative_to(ROOT))
            return 1
        print(f"{len(produced)} brand assets are up to date")
        return 0
    for path, image in produced.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
        print("wrote", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
