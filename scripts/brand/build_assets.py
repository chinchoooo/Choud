#!/usr/bin/env python3
"""Derives every platform asset from the supplied brand SVGs in `choud-brand-assets/`.

Nothing here redraws the logo: the SVGs are the source of truth, and this script only
copies them, converts their geometry, or rasterises them.

    python scripts/brand/build_assets.py            # regenerate everything
    python scripts/brand/build_assets.py --check    # fail if the committed assets are stale

Needs: Python 3.9+, Pillow (`pip install pillow`) and Google Chrome or Edge (headless, for
rasterising SVGs exactly as a browser draws them). Set CHROME=/path/to/chrome if it is not found.
See docs/branding.md for what is produced and why.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "choud-brand-assets"
WEB_PUBLIC = ROOT / "web" / "public"
WEB_BRAND = ROOT / "web" / "src" / "assets" / "brand"
RES = ROOT / "android" / "app" / "src" / "main" / "res"

SVG_NS = "{http://www.w3.org/2000/svg}"
ART_BOX = 64.0  # the SVGs are drawn on a 64 x 64 grid

# Android adaptive icons are cropped to a shape; only the middle ~61% is guaranteed visible. The
# farthest point of the cloud from its centre (32, 30) is ~28.7 grid units, so scaling the grid by
# 1.12 dp/unit keeps every pixel of it inside the 66 dp safe circle (33 / 28.7 = 1.15).
ADAPTIVE_SCALE = 1.12
ART_CENTER = (32.0, 30.0)


# ----------------------------------------------------------------------------- helpers


def find_chrome() -> str:
    candidates = [
        os.environ.get("CHROME", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    for name in ("google-chrome", "chromium", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Chrome/Edge not found: set the CHROME environment variable to its path.")


def strip_details(svg_text: str) -> str:
    """Drops the 1.6-unit dither dots: below ~48 px they stop being dots and become noise."""
    return re.sub(r'<rect x="[\d.]+" y="[\d.]+" width="1\.6" height="1\.6" fill="#[0-9A-Fa-f]{6}"/>', "", svg_text)


def raster_html(svg_path: Path, width: int, height: int, *, box: tuple[float, float, float] | None,
                background: str) -> str:
    """A page that draws `svg_path` at exactly width x height, or at `box` = (left, top, size)."""
    uri = svg_path.resolve().as_uri()
    if box is None:
        placement = f'width="{width}" height="{height}"'
        style = ""
    else:
        left, top, size = box
        placement = f'width="{size}" height="{size}"'
        style = f"position:absolute;left:{left}px;top:{top}px;"
    return (
        f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:{background};'
        f'position:relative;width:{width}px;height:{height}px;overflow:hidden">'
        f'<img src="{uri}" {placement} style="{style}display:block">'
    )


class Rasteriser:
    def __init__(self) -> None:
        self.chrome = find_chrome()
        self.tmp = Path(tempfile.mkdtemp(prefix="choud-brand-"))

    def png(self, svg: Path, out: Path, width: int, height: int | None = None, *,
            box: tuple[float, float, float] | None = None, background: str = "transparent") -> None:
        height = height or width
        page = self.tmp / f"{out.stem}.html"
        page.write_text(raster_html(svg, width, height, box=box, background=background), encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                self.chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=1", "--default-background-color=00000000",
                f"--window-size={width},{height}", f"--screenshot={out}", page.as_uri(),
            ],
            check=True, capture_output=True, timeout=120,
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def luminance_to_alpha(src: Path, out: Path) -> None:
    """White-on-black art -> white with transparency (what Android monochrome/status icons use)."""
    from PIL import Image

    image = Image.open(src).convert("L")
    result = Image.new("RGBA", image.size, (255, 255, 255, 0))
    result.putalpha(image)
    result.save(out)


# ----------------------------------------------------------------------------- SVG -> VectorDrawable


def _android_color(hex_value: str) -> str:
    return "#FF" + hex_value.lstrip("#").upper()


def svg_to_vector_drawable(svg_text: str, *, scale: float, translate: tuple[float, float],
                           size_dp: int, viewport: float) -> str:
    """Ports the shapes of an SVG (rects and paths only) to an Android VectorDrawable.

    The full-size background rect is skipped (the adaptive icon supplies its own background
    layer), and the `<text>` wordmark is not ported (logos with text ship as PNG instead).
    """
    root = ET.fromstring(svg_text)
    paths: list[str] = []
    for node in root.iter():
        tag = node.tag.replace(SVG_NS, "")
        if tag == "rect":
            if float(node.get("width", 0)) >= ART_BOX and float(node.get("height", 0)) >= ART_BOX:
                continue  # the background tile
            x, y = node.get("x", "0"), node.get("y", "0")
            w, h = node.get("width"), node.get("height")
            data = f"M{x},{y}h{w}v{h}h-{w}z"
            paths.append(f'        <path android:fillColor="{_android_color(node.get("fill", "#000000"))}" '
                         f'android:pathData="{data}"/>')
        elif tag == "path":
            attrs = []
            fill = node.get("fill", "none")
            if fill != "none":
                attrs.append(f'android:fillColor="{_android_color(fill)}"')
            stroke = node.get("stroke")
            if stroke:
                attrs.append(f'android:strokeColor="{_android_color(stroke)}"')
                attrs.append(f'android:strokeWidth="{node.get("stroke-width", "1")}"')
                attrs.append('android:strokeLineJoin="miter"')
            attrs.append(f'android:pathData="{node.get("d")}"')
            paths.append("        <path " + " ".join(attrs) + "/>")
    tx, ty = translate
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Generated by scripts/brand/build_assets.py from the supplied choud-brand-assets SVG. -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    android:width="{size_dp}dp"\n    android:height="{size_dp}dp"\n'
        f'    android:viewportWidth="{viewport:g}"\n    android:viewportHeight="{viewport:g}">\n'
        f'    <group android:scaleX="{scale:g}" android:scaleY="{scale:g}"\n'
        f'        android:translateX="{tx:g}" android:translateY="{ty:g}">\n'
        + "\n".join(paths)
        + "\n    </group>\n</vector>\n"
    )


# ----------------------------------------------------------------------------- targets


def build_web(r: Rasteriser) -> list[Path]:
    produced: list[Path] = []
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    WEB_BRAND.mkdir(parents=True, exist_ok=True)

    # The supplied SVGs, byte for byte: the favicon is served as-is from /favicon.svg and the
    # logos/icons are imported by the app (Vite hashes and caches them).
    shutil.copyfile(SRC / "choud-favicon.svg", WEB_PUBLIC / "favicon.svg")
    produced.append(WEB_PUBLIC / "favicon.svg")
    for name in ("choud-logo-dark", "choud-logo-light", "choud-icon-dark", "choud-icon-light"):
        shutil.copyfile(SRC / f"{name}.svg", WEB_BRAND / f"{name}.svg")
        produced.append(WEB_BRAND / f"{name}.svg")

    # PNG fallbacks. 16/32 px use the dot-free variant so they stay crisp; larger ones use the
    # artwork exactly as supplied.
    simple = r.tmp / "choud-favicon-simple.svg"
    simple.write_text(strip_details((SRC / "choud-favicon.svg").read_text(encoding="utf-8")), encoding="utf-8")
    for size in (16, 32):
        out = WEB_PUBLIC / f"favicon-{size}.png"
        r.png(simple, out, size, background="#000")
        produced.append(out)
    for name, size, svg in (
        ("apple-touch-icon.png", 180, SRC / "choud-favicon.svg"),  # square: iOS applies its own corners
        ("icon-192.png", 192, SRC / "choud-icon-dark.svg"),
        ("icon-512.png", 512, SRC / "choud-icon-dark.svg"),
    ):
        out = WEB_PUBLIC / name
        r.png(svg, out, size)
        produced.append(out)

    manifest = WEB_PUBLIC / "manifest.webmanifest"
    manifest.write_text(
        '{\n  "name": "Choud",\n  "short_name": "Choud",\n'
        '  "description": "Your private cloud.",\n'
        '  "start_url": "/files",\n  "scope": "/",\n  "display": "standalone",\n'
        '  "background_color": "#000000",\n  "theme_color": "#000000",\n'
        '  "icons": [\n'
        '    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },\n'
        '    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },\n'
        '    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml" }\n'
        "  ]\n}\n",
        encoding="utf-8",
    )
    produced.append(manifest)
    return produced


def build_android(r: Rasteriser) -> list[Path]:
    produced: list[Path] = []
    for folder in ("drawable", "drawable-nodpi", "values", "mipmap-anydpi-v26"):
        (RES / folder).mkdir(parents=True, exist_ok=True)

    icon_dark = (SRC / "choud-icon-dark.svg").read_text(encoding="utf-8")

    # In-app mark (splash, login): the artwork at its native 64 grid.
    mark = RES / "drawable" / "ic_choud_mark.xml"
    mark.write_text(svg_to_vector_drawable(icon_dark, scale=1.0, translate=(0, 0), size_dp=64, viewport=64),
                    encoding="utf-8")
    produced.append(mark)

    # Adaptive launcher foreground: the same artwork scaled into the safe zone and centred.
    tx = 54 - ART_CENTER[0] * ADAPTIVE_SCALE
    ty = 54 - ART_CENTER[1] * ADAPTIVE_SCALE
    foreground = RES / "drawable" / "ic_choud_foreground.xml"
    foreground.write_text(
        svg_to_vector_drawable(icon_dark, scale=ADAPTIVE_SCALE, translate=(tx, ty), size_dp=108, viewport=108),
        encoding="utf-8",
    )
    produced.append(foreground)

    # Themed (monochrome) icon: Android uses only the alpha channel, so the black cut-outs have
    # to be transparent. Rasterise the dark icon at 4x density and turn luminance into alpha.
    px = 108 * 4
    raw = r.tmp / "mono-raw.png"
    r.png(SRC / "choud-favicon.svg", raw, px, box=(4 * tx, 4 * ty, 64 * ADAPTIVE_SCALE * 4), background="#000")
    mono = RES / "drawable-nodpi" / "ic_choud_monochrome.png"
    luminance_to_alpha(raw, mono)
    produced.append(mono)

    # Status-bar icon: monochrome again, drawn from the dot-free variant so it stays legible at
    # 24 dp, with just enough padding (the mark is nearly square).
    simple = r.tmp / "choud-icon-simple.svg"
    simple.write_text(strip_details((SRC / "choud-favicon.svg").read_text(encoding="utf-8")), encoding="utf-8")
    for density, size in (("mdpi", 24), ("hdpi", 36), ("xhdpi", 48), ("xxhdpi", 72), ("xxxhdpi", 96)):
        folder = RES / f"drawable-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        art = size * 0.92
        raw = r.tmp / f"stat-{density}.png"
        r.png(simple, raw, size, box=((size - art) / 2, (size - art) / 2 - size * 0.02, art), background="#000")
        out = folder / "ic_stat_choud.png"
        luminance_to_alpha(raw, out)
        produced.append(out)

    # The detailed logos (they contain the wordmark, so they are PNGs rendered from the SVG).
    for tone in ("dark", "light"):
        out = RES / "drawable-nodpi" / f"choud_logo_{tone}.png"
        r.png(SRC / f"choud-logo-{tone}.svg", out, 512, background="transparent")
        produced.append(out)

    colors = RES / "values" / "colors.xml"
    colors.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        '    <color name="choud_black">#FF000000</color>\n'
        '    <color name="choud_white">#FFFFFFFF</color>\n'
        '    <color name="choud_line">#FF333333</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )
    produced.append(colors)

    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        icon = RES / "mipmap-anydpi-v26" / name
        icon.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <background android:drawable="@color/choud_black" />\n'
            '    <foreground android:drawable="@drawable/ic_choud_foreground" />\n'
            '    <monochrome android:drawable="@drawable/ic_choud_monochrome" />\n'
            "</adaptive-icon>\n",
            encoding="utf-8",
        )
        produced.append(icon)

    # The window background shown the instant the app launches (before any of our UI exists).
    splash = RES / "drawable" / "choud_splash.xml"
    splash.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <item android:drawable="@color/choud_black" />\n'
        '    <item android:gravity="center" android:width="96dp" android:height="96dp"\n'
        '        android:drawable="@drawable/ic_choud_mark" />\n'
        "</layer-list>\n",
        encoding="utf-8",
    )
    produced.append(splash)

    # Retire the earlier placeholder icon.
    for stale in (RES / "drawable" / "ic_launcher_foreground.xml",):
        if stale.exists():
            stale.unlink()
    return produced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if regenerating would change any file")
    args = parser.parse_args()

    for required in ("choud-logo-dark.svg", "choud-logo-light.svg", "choud-icon-dark.svg",
                     "choud-icon-light.svg", "choud-favicon.svg"):
        if not (SRC / required).exists():
            sys.exit(f"missing {SRC / required}")

    before = {}
    if args.check:
        for folder in (WEB_PUBLIC, WEB_BRAND, RES):
            for path in folder.rglob("*"):
                if path.is_file():
                    before[path] = path.read_bytes()

    rasteriser = Rasteriser()
    try:
        produced = build_web(rasteriser) + build_android(rasteriser)
    finally:
        rasteriser.cleanup()

    if args.check:
        stale = [p for p in produced if before.get(p) != p.read_bytes()]
        if stale:
            print("stale brand assets (run scripts/brand/build_assets.py):")
            for path in stale:
                print("  ", path.relative_to(ROOT))
            return 1
    print(f"wrote {len(produced)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
