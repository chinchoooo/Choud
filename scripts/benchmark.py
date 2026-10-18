#!/usr/bin/env python3
# ruff: noqa: E501
"""Choud benchmark: repeatable numbers you can publish, and compare with other services' published tests.

Two kinds of measurement:

  gizmodo, cloudwards, custom
            Upload and download a set of files over a SIMULATED line of a chosen speed (a token bucket
            caps the client), and report how much of the line Choud actually uses. This is the same
            question the independent cloud-storage speed tests ask ("how long does a 5 GB folder take at
            100 Mbps?"), so the result is comparable: only the overhead of the service shows, because
            the line speed is fixed by us instead of by an ISP.

  latency   Time the individual API calls the apps make (list a folder, search, the library index with
            and without a 304, a thumbnail on its own versus a batch of 24, small uploads, an upload of
            bytes the server already has), as p50/p95/p99. Optionally add --rtt-ms to model a distant
            client: each request then waits that long first, which shows what removing round trips buys.

Run it from the machine you care about (the server itself measures the server and proxy; a laptop or a
phone-sized client over Tailscale measures the whole path):

    python3 -m venv /tmp/bench && /tmp/bench/bin/pip install httpx pillow
    /tmp/bench/bin/python scripts/benchmark.py --url http://localhost --email you@example.com \\
        --label arvismint all

It only creates files inside one new folder (`benchmark-<id>`), and deletes them (and purges them from the
trash) when it finishes, unless you pass --keep. Use a throwaway account on a real server if you prefer.
Needs Python 3.9+ and httpx; Pillow is optional (without it the thumbnail tests are skipped).
Results are printed as Markdown and written to benchmark-results-<label>.md and .json.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import inspect
import io
import json
import math
import os
import platform
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("This script needs httpx:  pip install httpx   (and optionally: pip install pillow)")

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

MIB = 1024 * 1024
BLOCK = 64 * 1024
SMALL_LIMIT = 20 * MIB  # the apps send anything larger in 5 MiB chunks
CHUNK = 5 * MIB
CHUNK_LANES = 3  # chunks in flight per large file; web/src/api/uploads.ts uses the same number

# Published tests we compare against (see docs/benchmarks.md for the sources and caveats).
PUBLISHED = {
    "gizmodo": {
        "name": "Gizmodo, 500 MB archive, 187.95 Mbps down / 19.69 Mbps up (Oct 2026)",
        "service": "Google Drive",
        "up_seconds": 3 * 60 + 33,
        "down_seconds": 24,
        "size_mb": 500,
        "up_mbps": 19.69,
        "down_mbps": 187.95,
    },
    "cloudwards": {
        "name": "Cloudwards, 5 GB mixed folder, capped at 100 Mbps (Oct 2026)",
        "service": "Google Drive",
        "up_seconds": 7 * 60 + 15,
        "down_seconds": 7 * 60 + 18,
        "size_mb": 5000,
        "up_mbps": 100.0,
        "down_mbps": 100.0,
    },
}


# ----------------------------------------------------------------------------- helpers


class Line:
    """A shared speed limit: all transfers together may not go faster than `mbps`."""

    def __init__(self, mbps: float | None) -> None:
        self.rate = mbps * 1_000_000 / 8 if mbps else None
        self.lock = threading.Lock()
        self.free_at = time.perf_counter()
        self.moved = 0  # bytes that have passed through, for the progress bar

    def take(self, nbytes: int) -> None:
        with self.lock:
            self.moved += nbytes
        if not self.rate:
            return
        with self.lock:
            now = time.perf_counter()
            start = max(now, self.free_at)
            self.free_at = start + nbytes / self.rate
            wait = self.free_at - now
        if wait > 0:
            time.sleep(wait)


def blob(seed: int, size: int):
    """Deterministic pseudo-random bytes in blocks (so a hash can be known before uploading)."""
    rng = random.Random(seed)
    left = size
    while left > 0:
        n = min(BLOCK, left)
        yield rng.randbytes(n)
        left -= n


def sha256_of(seed: int, size: int) -> str:
    digest = hashlib.sha256()
    for block in blob(seed, size):
        digest.update(block)
    return digest.hexdigest()


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]


class Api:
    def __init__(self, url: str, email: str, password: str, rtt_ms: float = 0.0) -> None:
        self.http = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=None,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
        )
        self.email, self.password = email, password
        self.rtt = rtt_ms / 1000.0
        self.logged_in_at = 0.0
        self.refresh_token = ""
        self.lock = threading.Lock()
        self.login()

    def login(self) -> None:
        reply = self.http.post(
            "/api/auth/login", json={"email": self.email, "password": self.password}
        )
        if reply.status_code != 200:
            sys.exit(f"login failed ({reply.status_code}): {reply.text[:200]}")
        body = reply.json()
        self.http.headers["Authorization"] = f"Bearer {body['access_token']}"
        self.refresh_token = body.get("refresh_token", "")
        self.logged_in_at = time.time()

    def fresh(self) -> None:
        """Access tokens last 15 minutes; renew well before that so long runs never see a 401."""
        if time.time() - self.logged_in_at < 600:
            return
        with self.lock:
            if time.time() - self.logged_in_at < 600:
                return
            reply = self.http.post("/api/auth/refresh", json={"refresh_token": self.refresh_token})
            if reply.status_code == 200:
                body = reply.json()
                self.http.headers["Authorization"] = f"Bearer {body['access_token']}"
                self.refresh_token = body.get("refresh_token", self.refresh_token)
                self.logged_in_at = time.time()
            else:
                self.login()

    def call(self, method: str, path: str, **kwargs) -> httpx.Response:
        self.fresh()
        if self.rtt:
            time.sleep(self.rtt)  # a simulated distance: the request "travels" before it is sent
        # A 429 means the server asked for a pause: wait as long as it says and try again, so one
        # throttled request does not end a long run. (Streamed bodies cannot be resent, so those
        # are retried only for requests without a generator body.)
        for attempt in range(6):
            reply = self.http.request(method, path, **kwargs)
            if reply.status_code != 429 or inspect.isgenerator(kwargs.get("content")):
                return reply
            time.sleep(min(30, int(reply.headers.get("retry-after", "2")) + attempt))
        return reply


def multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    size: int,
    blocks,
    line: Line,
    content_type: str = "application/octet-stream",
):
    """A streamed multipart/form-data body, paced by `line`. Returns (headers, generator)."""
    boundary = uuid.uuid4().hex
    head = b""
    for key, value in fields.items():
        head += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    head += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(head) + size + len(tail)),
    }

    def body():
        yield head
        for piece in blocks:
            line.take(len(piece))
            yield piece
        yield tail

    return headers, body()


# ----------------------------------------------------------------------------- transfers


def upload_file(api: Api, line: Line, folder_id: str, name: str, seed: int, size: int) -> str:
    """Uploads one deterministic file the way the apps do; returns its file id."""
    if size <= SMALL_LIMIT:
        headers, body = multipart(
            {"folder_id": folder_id, "name": name, "base_version_id": "none"},
            "file",
            name,
            size,
            blob(seed, size),
            line,
        )
        reply = api.call("POST", "/api/files/upload", headers=headers, content=body)
        if reply.status_code != 201:
            raise RuntimeError(f"upload {name}: {reply.status_code} {reply.text[:200]}")
        return reply.json()["id"]
    created = api.call(
        "POST",
        "/api/uploads",
        json={
            "file_name": name,
            "file_size": size,
            "chunk_size": CHUNK,
            "folder_id": folder_id,
            "expected_hash": sha256_of(seed, size),
            "base_version_id": "none",
        },
    )
    if created.status_code != 201:
        raise RuntimeError(f"session {name}: {created.status_code} {created.text[:200]}")
    session = created.json()["id"]
    index, sent = 0, 0
    stream = blob(seed, size)
    buffer = b""
    lanes = threading.BoundedSemaphore(CHUNK_LANES)  # the apps send a few chunks at once
    failures: list[str] = []

    def send(i: int, piece: bytes) -> None:
        try:
            headers, body = multipart({}, "chunk", "chunk", len(piece), iter([piece]), line)
            reply = api.call(
                "POST", f"/api/uploads/{session}/chunks/{i}", headers=headers, content=body
            )
            if reply.status_code != 200:
                failures.append(f"chunk {i} of {name}: {reply.status_code} {reply.text[:200]}")
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(f"chunk {i} of {name}: {exc}")
        finally:
            lanes.release()

    with ThreadPoolExecutor(CHUNK_LANES) as pool:
        while sent < size and not failures:
            want = min(CHUNK, size - sent)
            while len(buffer) < want:
                buffer += next(stream)
            piece, buffer = buffer[:want], buffer[want:]
            lanes.acquire()
            pool.submit(send, index, piece)
            sent += want
            index += 1
    if failures:
        raise RuntimeError(failures[0])
    done = api.call("POST", f"/api/uploads/{session}/complete")
    if done.status_code not in (200, 201):
        raise RuntimeError(f"complete {name}: {done.status_code} {done.text[:200]}")
    return done.json()["id"]


def download_file(api: Api, line: Line, file_id: str, expect_sha: str | None) -> int:
    api.fresh()
    digest = hashlib.sha256()
    total = 0
    for attempt in range(6):
        with api.http.stream("GET", f"/api/files/{file_id}/download") as reply:
            if reply.status_code == 429:  # the server asked for a pause; wait and ask again
                time.sleep(min(30, int(reply.headers.get("retry-after", "2")) + attempt))
                continue
            if reply.status_code != 200:
                raise RuntimeError(f"download {file_id}: {reply.status_code}")
            for piece in reply.iter_bytes(BLOCK):
                line.take(len(piece))
                digest.update(piece)
                total += len(piece)
            break
    else:
        raise RuntimeError(f"download {file_id}: still throttled (429) after retries")
    if expect_sha and digest.hexdigest() != expect_sha:
        raise RuntimeError(f"download {file_id}: the bytes do not match what was uploaded")
    return total


def profile(name: str, size_mb: float) -> list[tuple[str, int]]:
    """The files of a test: a name and a size in bytes each."""
    total = int(size_mb * 1_000_000)
    if name == "single":
        return [("single.bin", total)]
    # A mixed folder like the published 5 GB test: a few big videos, many photos, many small documents.
    videos = 6 if total >= 2_000_000_000 else 2
    video_each = int(total * 0.60) // videos
    photos = max(3, round(total * 0.24 / 8_000_000))
    photo_each = int(total * 0.24) // photos
    rest = total - videos * video_each - photos * photo_each
    docs = max(1, round(rest / 900_000))
    doc_each = rest // docs
    plan = [(f"video-{i:04d}.bin", video_each) for i in range(videos)]
    plan += [(f"photo-{i:04d}.bin", photo_each) for i in range(photos)]
    plan += [(f"doc-{i:04d}.bin", doc_each) for i in range(docs)]
    return plan


class Bar:
    """A one-line progress bar that redraws in place: phase, percent, bytes, speed and time left."""

    def __init__(self, phase: str, line: Line, total: int, files: int) -> None:
        self.phase, self.line, self.total, self.files = phase, line, total, files
        self.done_files = 0
        self.started = time.perf_counter()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def file_done(self) -> None:
        self.done_files += 1

    def __enter__(self) -> "Bar":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop.set()
        self.thread.join()
        self._draw(final=True)
        print(flush=True)

    def _run(self) -> None:
        while not self.stop.wait(0.5):
            self._draw()

    def _draw(self, final: bool = False) -> None:
        moved = min(self.line.moved, self.total)
        fraction = moved / self.total if self.total else 1.0
        elapsed = time.perf_counter() - self.started
        speed = moved / elapsed if elapsed > 0 else 0.0
        left = (self.total - moved) / speed if speed > 0 and not final else 0.0
        width = 28
        filled = int(width * fraction)
        bar = "#" * filled + "-" * (width - filled)
        print(
            f"\r   {self.phase:<8} [{bar}] {fraction * 100:5.1f}%  "
            f"{moved / 1e6:7.0f}/{self.total / 1e6:.0f} MB  {speed * 8 / 1e6:6.1f} Mbps  "
            f"files {self.done_files}/{self.files}  {fmt_time(elapsed)} (left {fmt_time(left)})   ",
            end="",
            flush=True,
        )


def run_paced(
    api: Api,
    folder: str,
    label: str,
    up_mbps: float,
    down_mbps: float,
    files: list[tuple[str, int]],
    workers: int,
):
    total = sum(size for _, size in files)
    print(
        f"\n== paced: {label}: {len(files)} file(s), {total / 1e6:.0f} MB, up {up_mbps} Mbps, down {down_mbps} Mbps, {workers} parallel",
        flush=True,
    )
    seeds = {name: random.Random(name).randrange(1 << 30) for name, _ in files}
    shas = (
        {name: sha256_of(seeds[name], size) for name, size in files} if total <= 600_000_000 else {}
    )
    up_line, down_line = Line(up_mbps), Line(down_mbps)
    ids: dict[str, str] = {}
    start = time.perf_counter()
    with Bar("upload", up_line, total, len(files)) as bar, ThreadPoolExecutor(workers) as pool:

        def up(item):
            name, size = item
            ids[name] = upload_file(api, up_line, folder, name, seeds[name], size)
            bar.file_done()

        list(pool.map(up, files))
    up_seconds = time.perf_counter() - start
    # Printed now, so a failure in the download half cannot lose it.
    up_min_now = total * 8 / (up_mbps * 1e6) if up_mbps else 0
    if up_seconds:
        print(
            f"   upload   {fmt_time(up_seconds)} (line minimum {fmt_time(up_min_now)}, "
            f"{round(100 * up_min_now / up_seconds, 1)}% of the line)",
            flush=True,
        )
    start = time.perf_counter()
    with Bar("download", down_line, total, len(files)) as bar, ThreadPoolExecutor(workers) as pool:

        def down(item):
            got_bytes = download_file(api, down_line, ids[item[0]], shas.get(item[0]))
            bar.file_done()
            return got_bytes

        got = list(pool.map(down, files))
    down_seconds = time.perf_counter() - start
    assert sum(got) == total, "downloaded byte count differs from uploaded"
    up_min = total * 8 / (up_mbps * 1e6) if up_mbps else 0
    down_min = total * 8 / (down_mbps * 1e6) if down_mbps else 0
    result = {
        "label": label,
        "files": len(files),
        "bytes": total,
        "up_mbps": up_mbps,
        "down_mbps": down_mbps,
        "workers": workers,
        "up_seconds": round(up_seconds, 2),
        "down_seconds": round(down_seconds, 2),
        "up_theoretical_seconds": round(up_min, 2),
        "down_theoretical_seconds": round(down_min, 2),
        "up_line_used_pct": round(100 * up_min / up_seconds, 1) if up_seconds else None,
        "down_line_used_pct": round(100 * down_min / down_seconds, 1) if down_seconds else None,
        "hash_verified_on_download": bool(shas),
    }
    print(
        f"   upload   {fmt_time(up_seconds)} (line minimum {fmt_time(up_min)}, {result['up_line_used_pct']}% of the line)"
    )
    print(
        f"   download {fmt_time(down_seconds)} (line minimum {fmt_time(down_min)}, {result['down_line_used_pct']}% of the line)"
    )
    return result, list(ids.values())


# ----------------------------------------------------------------------------- latency


def timed(fn, count: int) -> list[float]:
    out = []
    for _ in range(count):
        started = time.perf_counter()
        fn()
        out.append((time.perf_counter() - started) * 1000)
    return out


def jpeg(seed: int, width: int = 1600, height: int = 1200) -> bytes:
    rng = random.Random(seed)
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    step = 8
    for x in range(0, width, step):
        for y in range(0, height, step):
            color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for dx in range(step):
                for dy in range(step):
                    if x + dx < width and y + dy < height:
                        pixels[x + dx, y + dy] = color
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def run_latency(api: Api, folder: str, n_files: int, rtt_ms: float):
    print(f"\n== latency: {n_files} files, simulated extra round trip {rtt_ms} ms", flush=True)
    rows: dict[str, list[float]] = {}
    created: list[str] = []
    line = Line(None)

    def record(name: str, samples: list[float]) -> None:
        rows[name] = samples
        print(
            f"   {name:<46} p50 {pct(samples, 50):8.1f} ms   p95 {pct(samples, 95):8.1f} ms   n={len(samples)}",
            flush=True,
        )

    record("GET /api/health", timed(lambda: api.call("GET", "/api/health"), 100))

    # Small uploads (100 KB): the cost of one file arriving.
    small = 100 * 1024
    counter = iter(range(10_000_000))

    def one_upload() -> None:
        i = next(counter)
        created.append(upload_file(api, line, folder, f"small-{i:05d}.bin", i, small))

    record("upload 100 KB (new bytes)", timed(one_upload, 60))

    # Uploading bytes the server already holds (deduplication: nothing new is written).
    same = 777

    def dup_upload() -> None:
        i = next(counter)
        created.append(upload_file(api, line, folder, f"dup-{i:05d}.bin", same, small))

    upload_file(api, line, folder, "dup-first.bin", same, small)
    record("upload 100 KB (bytes the server already has)", timed(dup_upload, 60))

    # A folder with many files, then listing and searching it.
    needed = max(0, n_files - len(created))
    with ThreadPoolExecutor(8) as pool:
        list(
            pool.map(
                lambda i: created.append(
                    upload_file(api, line, folder, f"list-{i:05d}.bin", 10_000 + i, 4096)
                ),
                range(needed),
            )
        )
    record(
        f"list a folder of ~{len(created)} files",
        timed(lambda: api.call("GET", "/api/files", params={"folder_id": folder}), 40),
    )
    record(
        "search by name",
        timed(lambda: api.call("GET", "/api/search", params={"q": "list-0001"}), 40),
    )

    # The library index: everything (full) and "nothing changed" (a 304).
    full = api.call("GET", "/api/library/index")
    etag = full.headers.get("etag", "")
    rows_in_library = len(full.json().get("rows", [])) if full.status_code == 200 else 0
    record(
        f"library index, full ({rows_in_library} photos/videos in the account)",
        timed(lambda: api.call("GET", "/api/library/index"), 15),
    )
    record(
        "library index, nothing changed (304)",
        timed(lambda: api.call("GET", "/api/library/index", headers={"If-None-Match": etag}), 40),
    )

    # Thumbnails: one at a time versus one batch, the heart of the fast-photos design.
    if Image is None:
        print("   (Pillow is not installed: skipping the thumbnail tests)")
        return rows, created, {}
    photo_ids = []
    with ThreadPoolExecutor(6) as pool:

        def make(i: int) -> str:
            data = jpeg(i)
            headers, body = multipart(
                {"folder_id": folder, "name": f"photo-{i:03d}.jpg", "base_version_id": "none"},
                "file",
                f"photo-{i:03d}.jpg",
                len(data),
                iter([data]),
                line,
                "image/jpeg",
            )
            reply = api.http.post("/api/files/upload", headers=headers, content=body)
            return reply.json()["id"]

        photo_ids = list(pool.map(make, range(24)))
    created += photo_ids
    for _ in range(40):  # make sure every thumbnail exists, so we time delivery and not generation
        reply = api.http.post(
            "/api/media/thumbs", json={"ids": photo_ids, "size": 256, "format": "webp"}
        )
        if reply.status_code == 200 and all(
            status == 0 for status in frame_statuses(reply.content)
        ):
            break
        time.sleep(0.5)
    record(
        "one thumbnail (WebP 256 px, stable URL)",
        timed(
            lambda: api.call(
                "GET", f"/api/thumbs/{photo_ids[0]}", params={"size": 256, "format": "webp"}
            ),
            60,
        ),
    )

    def twenty_four_singles() -> None:
        for fid in photo_ids:
            api.call("GET", f"/api/thumbs/{fid}", params={"size": 256, "format": "webp"})

    def one_batch() -> None:
        api.call(
            "POST", "/api/media/thumbs", json={"ids": photo_ids, "size": 256, "format": "webp"}
        )

    record("a screen of 24 thumbnails: 24 separate requests", timed(twenty_four_singles, 10))
    record("a screen of 24 thumbnails: ONE batch request", timed(one_batch, 30))
    sizes = {
        "webp_256_bytes": len(
            api.http.get(
                f"/api/thumbs/{photo_ids[0]}", params={"size": 256, "format": "webp"}
            ).content
        ),
        "jpeg_256_bytes": len(
            api.http.get(
                f"/api/thumbs/{photo_ids[0]}", params={"size": 256, "format": "jpg"}
            ).content
        ),
    }
    return rows, created, sizes


def frame_statuses(data: bytes) -> list[int]:
    out, pos = [], 0
    while pos + 21 <= len(data):
        status = data[pos + 16]
        length = int.from_bytes(data[pos + 17 : pos + 21], "big")
        out.append(status)
        pos += 21 + length
    return out


# ----------------------------------------------------------------------------- report


def render(info: dict, paced: list[dict], latency: dict | None, extra: dict) -> str:
    lines = [f"# Choud benchmark: {info['label']}", ""]
    lines += [
        f"- Run: {info['when']}",
        f"- Machine running the test: {info['machine']}",
        f"- Server: {info['server']}   URL: {info['url']}   Simulated extra round trip: {info['rtt_ms']} ms",
        "",
    ]
    if paced:
        lines += [
            "## Transfers over a simulated line",
            "",
            "| Test | Size | Line | Choud up | Choud down | Up, % of line | Down, % of line |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in paced:
            lines.append(
                f"| {r['label']} | {r['bytes'] / 1e6:.0f} MB, {r['files']} file(s) | {r['up_mbps']} / {r['down_mbps']} Mbps | "
                f"{fmt_time(r['up_seconds'])} | {fmt_time(r['down_seconds'])} | {r['up_line_used_pct']}% | {r['down_line_used_pct']}% |"
            )
        lines += [
            "",
            "### Against the published tests (a different network, machine and file set each; indicative only)",
            "",
            "| Test | Service | Upload | Download | Up, % of line | Down, % of line |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in paced:
            ref = PUBLISHED.get(r["label"])
            if not ref:
                continue
            up_min = ref["size_mb"] * 8 / ref["up_mbps"]
            down_min = ref["size_mb"] * 8 / ref["down_mbps"]
            lines.append(
                f"| {ref['name']} | {ref['service']} | {fmt_time(ref['up_seconds'])} | {fmt_time(ref['down_seconds'])} | {100 * up_min / ref['up_seconds']:.0f}% | {100 * down_min / ref['down_seconds']:.0f}% |"
            )
            lines.append(
                f"| same test | **Choud** | {fmt_time(r['up_seconds'])} | {fmt_time(r['down_seconds'])} | {r['up_line_used_pct']}% | {r['down_line_used_pct']}% |"
            )
        lines.append("")
    if latency:
        lines += [
            "## API latency (milliseconds)",
            "",
            "| Call | p50 | p95 | p99 | max | n |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for name, samples in latency.items():
            lines.append(
                f"| {name} | {pct(samples, 50):.1f} | {pct(samples, 95):.1f} | {pct(samples, 99):.1f} | {max(samples):.1f} | {len(samples)} |"
            )
        lines.append("")
        if extra:
            lines.append(
                f"Thumbnail sizes: WebP {extra.get('webp_256_bytes')} bytes, JPEG {extra.get('jpeg_256_bytes')} bytes."
            )
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "scenario",
        choices=["gizmodo", "cloudwards", "custom", "latency", "all"],
        help="gizmodo / cloudwards: re-run that published test; custom: your own size and line speed; latency: per-call timings; all: gizmodo + cloudwards + latency",
    )
    parser.add_argument(
        "--url",
        default="http://localhost",
        help="the server's address (the proxy, as the apps use it)",
    )
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        default=os.environ.get("CHOUD_PASSWORD"),
        help="or set CHOUD_PASSWORD; otherwise you are asked",
    )
    parser.add_argument(
        "--label", default="run", help="a name for this machine/run, used in the output file names"
    )
    parser.add_argument(
        "--rtt-ms",
        type=float,
        default=0.0,
        help="simulate a distant client: wait this long before every request",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="parallel transfers, like the desktop apps"
    )
    parser.add_argument(
        "--files", type=int, default=500, help="files in the folder used for the listing test"
    )
    parser.add_argument("--up-mbps", type=float, help="for the custom scenario: upload line speed")
    parser.add_argument(
        "--down-mbps", type=float, help="for the custom scenario: download line speed"
    )
    parser.add_argument(
        "--size-mb", type=float, help="for the custom scenario: total size in MB (decimal)"
    )
    parser.add_argument("--profile", choices=["single", "mixed"], default="single")
    parser.add_argument(
        "--keep", action="store_true", help="do not delete the files the benchmark created"
    )
    args = parser.parse_args()
    password = args.password or getpass.getpass("Password: ")

    api = Api(args.url, args.email, password, args.rtt_ms)
    server = "unknown"
    reply = api.http.get("/api/instance")
    if reply.status_code == 200:
        server = f"Choud {reply.json().get('version', '?')}"
    folder_reply = api.http.post("/api/folders", json={"name": f"benchmark-{uuid.uuid4().hex[:8]}"})
    folder_reply.raise_for_status()
    folder = folder_reply.json()["id"]

    run_paced_tests: list[dict] = []
    latency = None
    extra: dict = {}
    created: list[str] = []
    try:
        wanted = {
            "gizmodo": ["gizmodo"],
            "cloudwards": ["cloudwards"],
            "all": ["gizmodo", "cloudwards"],
        }.get(args.scenario, [])
        if args.scenario == "custom":
            if not (args.size_mb and args.up_mbps):
                sys.exit(
                    "custom needs --size-mb and --up-mbps (and optionally --down-mbps, --profile)"
                )
            files = profile(args.profile, args.size_mb)
            result, ids = run_paced(
                api,
                folder,
                "custom",
                args.up_mbps,
                args.down_mbps or args.up_mbps,
                files,
                args.workers,
            )
            run_paced_tests.append(result)
            created += ids
        for key in wanted:
            ref = PUBLISHED[key]
            files = profile("single" if key == "gizmodo" else "mixed", ref["size_mb"])
            result, ids = run_paced(
                api,
                folder,
                key,
                ref["up_mbps"],
                ref["down_mbps"],
                files,
                1 if key == "gizmodo" else args.workers,
            )
            run_paced_tests.append(result)
            created += ids
        if args.scenario in ("latency", "all"):
            latency, ids, extra = run_latency(api, folder, args.files, args.rtt_ms)
            created += ids
    finally:
        if not args.keep:
            print("\nCleaning up the benchmark folder...", flush=True)
            with ThreadPoolExecutor(8) as pool:
                list(pool.map(lambda fid: api.http.delete(f"/api/files/{fid}"), set(created)))
                list(pool.map(lambda fid: api.http.delete(f"/api/trash/{fid}"), set(created)))
            api.http.delete(f"/api/folders/{folder}")

    info = {
        "label": args.label,
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "machine": f"{platform.platform()}, {os.cpu_count()} logical CPUs, Python {platform.python_version()}",
        "server": server,
        "url": args.url,
        "rtt_ms": args.rtt_ms,
    }
    report = render(info, run_paced_tests, latency, extra)
    print("\n" + report)
    stem = f"benchmark-results-{args.label}"
    with open(stem + ".md", "w", encoding="utf-8") as handle:
        handle.write(report)
    with open(stem + ".json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "info": info,
                "paced": run_paced_tests,
                "latency_ms": {
                    k: {
                        "p50": pct(v, 50),
                        "p95": pct(v, 95),
                        "p99": pct(v, 99),
                        "max": max(v),
                        "n": len(v),
                        "samples": v,
                    }
                    for k, v in (latency or {}).items()
                },
                "extra": extra,
            },
            handle,
            indent=2,
        )
    print(f"\nWrote {stem}.md and {stem}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
