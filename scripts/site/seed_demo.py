#!/usr/bin/env python3
"""Fills a THROWAWAY dev server with demo data, so the website's screenshots show a lived-in drive
without any personal files.

    pip install httpx pillow
    python scripts/site/seed_demo.py --url http://localhost:8080

The server must allow open registration (start the dev stack with REGISTRATION_MODE=open), and this
must never be pointed at a real drive: it creates an account and uploads dozens of files.

Photos are public-domain images from NASA (https://images.nasa.gov). They are re-saved with Pillow so
no metadata is carried over, and given spread-out dates so the photo timeline looks real.
"""

import argparse
import io
import os
import json
import random
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from PIL import Image

EMAIL = os.environ.get("DEMO_EMAIL", "sitedemo@example.com")
PASSWORD = "demo-password-123"
QUERIES = [
    "hubble nebula",
    "hubble galaxy",
    "earth from the international space station",
    "aurora from orbit",
    "saturn cassini",
    "jupiter juno",
    "mars surface panorama",
    "lunar surface",
]
# Public site, so no pictures of people or places: anything whose title or description mentions
# these words is skipped, and every chosen image is still checked by eye before it is published.
PEOPLE = (
    "astronaut crew people person man woman girl boy child kid student teacher team scientist family "
    "ceremony sign building portrait visit event award speaker audience launch pad suit costume mascot "
    "employee staff director administrator selfie"
).split()
CACHE = Path(__file__).with_name("nasa-cache")


def nasa_images(want: int) -> list[bytes]:
    CACHE.mkdir(exist_ok=True)
    cached = sorted(CACHE.glob("*.jpg"))
    if len(cached) >= want:
        return [p.read_bytes() for p in cached[:want]]
    found: list[bytes] = []
    per_query = max(3, want // len(QUERIES) + 2)
    for query in QUERIES:
        url = (
            "https://images-api.nasa.gov/search?media_type=image&page_size=%d&q=%s"
            % (per_query, urllib.request.quote(query))
        )
        with urllib.request.urlopen(url, timeout=30) as reply:
            items = json.loads(reply.read().decode("utf-8"))["collection"]["items"]
        for item in items:
            text = " ".join(
                [item["data"][0].get("title", ""), item["data"][0].get("description", "") or ""]
            ).lower()
            if any(word in text.split() or word in text for word in PEOPLE):
                continue
            links = [lk["href"] for lk in item.get("links", []) if lk.get("render") == "image"]
            if not links:
                continue
            try:
                with urllib.request.urlopen(links[0].replace(" ", "%20"), timeout=30) as img:
                    raw = img.read()
                # re-save: drops EXIF and any other metadata
                picture = Image.open(io.BytesIO(raw)).convert("RGB")
                picture.thumbnail((1600, 1600))
                out = io.BytesIO()
                picture.save(out, "JPEG", quality=86)
                found.append(out.getvalue())
                (CACHE / f"{len(found):03d}.jpg").write_bytes(out.getvalue())
            except Exception as exc:  # noqa: BLE001 - skip one bad image, keep going
                print("skipped an image:", exc, file=sys.stderr)
            if len(found) >= want:
                return found
    return found


class Demo:
    def __init__(self, url: str) -> None:
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=120)
        self.login()

    def login(self) -> None:
        body = {"username": EMAIL.split("@")[0], "email": EMAIL, "password": PASSWORD}
        reg = self.http.post("/api/auth/register", json=body)
        if reg.status_code not in (200, 201, 409):
            sys.exit(f"register failed: {reg.status_code} {reg.text[:200]}")
        reply = self.http.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        if reply.status_code != 200:
            sys.exit(f"login failed: {reply.status_code} {reply.text[:200]}")
        self.http.headers["Authorization"] = "Bearer " + reply.json()["access_token"]

    def folder(self, name: str, parent: str | None = None) -> str:
        reply = self.http.post("/api/folders", json={"name": name, "parent_id": parent})
        if reply.status_code == 409:  # already there from an earlier run
            listing = self.http.get("/api/files", params={"folder_id": parent} if parent else {})
            for sub in listing.json()["subfolders"]:
                if sub["name"] == name:
                    return sub["id"]
        reply.raise_for_status()
        return reply.json()["id"]

    def upload(self, name, data, folder=None, when=None, mime="application/octet-stream") -> dict:
        fields = {"name": name}
        if folder:
            fields["folder_id"] = folder
        if when:
            fields["taken_at"] = when.isoformat()
            fields["modified_at"] = when.isoformat()
        reply = self.http.post(
            "/api/files/upload", data=fields, files={"file": (name, data, mime)}
        )
        reply.raise_for_status()
        return reply.json()


def document_pdf(title: str, lines: list[str]) -> bytes:
    """A real, tiny PDF made with Pillow (so search can find words inside it)."""
    page = Image.new("RGB", (1240, 1754), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(page)
    draw.text((100, 100), title, fill="black")
    for i, line in enumerate(lines):
        draw.text((100, 200 + i * 40), line, fill="black")
    out = io.BytesIO()
    page.save(out, "PDF")
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--photos", type=int, default=48)
    args = parser.parse_args()

    rng = random.Random(7)
    demo = Demo(args.url)
    photos_dir = demo.folder("Photos")
    trips = [demo.folder(name, photos_dir) for name in ("Observatory trip", "Backyard nights", "Road to the coast")]
    docs_dir = demo.folder("Documents")
    work = demo.folder("Projects", docs_dir)

    images = nasa_images(args.photos)  # the cache is curated by hand; see the module docstring
    print(f"uploading {len(images)} photos")
    end = datetime(2026, 9, 20, tzinfo=timezone.utc)
    for i, data in enumerate(images):
        # most photos from the last few months, so the timeline has real rows; a few older ones
        back = rng.randrange(100) if i % 6 else 100 + rng.randrange(900)
        when = end - timedelta(days=back, hours=rng.randrange(24), minutes=rng.randrange(60))
        folder = trips[i % len(trips)] if i % 3 else photos_dir
        demo.upload(f"IMG_{when:%Y%m%d}_{i:04d}.jpg", data, folder, when, "image/jpeg")

    print("uploading documents")
    notes = demo.upload(
        "trip-notes.txt",
        b"Observatory trip. We left at six, the telescope booking was for nine.\nRemember the red torch and the thermos.\n",
        docs_dir,
        mime="text/plain",
    )
    plan = demo.upload(
        "launch-plan.txt",
        b"Launch plan, version one: write the guide, record the demo, publish the release notes.\n",
        work,
        mime="text/plain",
    )
    # a second and third upload under the same name make versions 2 and 3
    demo.upload(
        "launch-plan.txt",
        b"Launch plan, version two: write the guide, record the demo, publish the release notes, ask two friends to try it.\n",
        work,
        mime="text/plain",
    )
    demo.upload(
        "launch-plan.txt",
        b"Launch plan, version three: guide done, demo recorded, release notes drafted, two friends tried it and found three bugs.\n",
        work,
        mime="text/plain",
    )
    demo.upload(
        "telescope-manual.pdf",
        document_pdf("Telescope manual", ["Align the finder scope at dusk.", "Never point the telescope at the sun."]),
        docs_dir,
        mime="application/pdf",
    )

    # three files to the trash
    for i in range(3):
        extra = demo.upload(f"old-draft-{i + 1}.txt", f"an old draft {i + 1}\n".encode(), docs_dir, mime="text/plain")
        demo.http.delete(f"/api/files/{extra['id']}").raise_for_status()

    # a link with an expiry and a password, and a favourite
    link = demo.http.post(
        "/api/shares",
        json={"file_id": notes["id"], "expires_in_hours": 72, "password": "stargazer", "label": "Notes for the trip"},
    )
    link.raise_for_status()
    demo.http.put(f"/api/library/favorites/{plan['id']}")
    print("done. Sign in as", EMAIL, "with password", PASSWORD)


if __name__ == "__main__":
    main()
