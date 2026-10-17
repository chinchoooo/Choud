"""The HTML a visitor sees on a public link. Plain server-rendered pages, no JavaScript.

Everything that comes from a user (file and folder names) goes through `html.escape`, and the
pages are sent with a Content-Security-Policy that forbids scripts entirely, so even a file named
`<script>...` could not run anything.
"""

import html
import uuid

from app.models.file import File
from app.models.folder import Folder

# No script of any kind; images/media only from this same origin; forms only back to this origin.
CSP = (
    "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

PAGE_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
}

_STYLE = """
body{background:#000;color:#fff;font:14px/1.6 "Cascadia Mono","JetBrains Mono",Consolas,"Courier New",monospace;margin:0;padding:24px}
.box{max-width:760px;margin:0 auto;border:1px solid #fff;padding:20px}
h1{font-size:15px;margin:0 0 4px;letter-spacing:.06em}
.muted{color:#aaa}
a{color:#fff}
a.btn,button{display:inline-block;background:#fff;color:#000;border:1px solid #fff;padding:6px 14px;font:inherit;cursor:pointer;text-decoration:none}
a.btn:hover,button:hover{background:#000;color:#fff}
input{background:#000;color:#fff;border:1px solid #fff;padding:6px 10px;font:inherit}
hr{border:0;border-top:1px dashed #555;margin:16px 0}
ul{list-style:none;margin:0;padding:0}
li{display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px dashed #333}
li .grow{flex:1;min-width:0;overflow-wrap:anywhere}
img.thumb{width:48px;height:48px;object-fit:cover;border:1px solid #444}
img.preview,video.preview{max-width:100%;max-height:60vh;border:1px solid #444;background:#111}
.err{color:#fff;border:1px solid #fff;padding:6px 10px;margin:12px 0}
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def page(body: str, title: str = "Choud") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{_e(title)}</title>'
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
        f'<style>{_STYLE}</style></head><body><main class="box">{body}</main></body></html>'
    )


def not_found() -> str:
    return page(
        "<h1>CHOUD</h1><p>This link doesn't exist or has expired.</p>"
        '<p class="muted">Ask whoever sent it for a new one.</p>',
        "Link not found",
    )


def unlock_form(token: str, *, error: bool = False) -> str:
    message = '<p class="err">That password is not right.</p>' if error else ""
    return page(
        "<h1>CHOUD</h1><p>This link is protected. Enter the password to continue.</p>"
        f"{message}"
        f'<form method="post" action="/s/{_e(token)}/unlock">'
        '<input type="password" name="password" autocomplete="current-password" '
        'autofocus required aria-label="Password"> <button type="submit">[ OPEN ]</button>'
        "</form>",
        "Password required",
    )


_INLINE_KINDS = ("image/", "video/", "audio/")


def file_page(token: str, file: File, inline_ok: bool) -> str:
    url = f"/s/{_e(token)}/file/{file.id}"
    mime = (file.mime_type or "").split(";")[0].strip().lower()
    preview = ""
    if inline_ok and mime.startswith("image/"):
        preview = f'<p><img class="preview" src="{url}?inline=1" alt="{_e(file.name)}"></p>'
    elif inline_ok and mime.startswith("video/"):
        preview = f'<p><video class="preview" src="{url}?inline=1" controls></video></p>'
    elif inline_ok and mime.startswith("audio/"):
        preview = f'<p><audio src="{url}?inline=1" controls></audio></p>'
    return page(
        f"<h1>{_e(file.name)}</h1>"
        f'<p class="muted">{_size(file.size)}</p>{preview}'
        f'<p><a class="btn" href="{url}">[ DOWNLOAD ]</a></p>',
        file.name,
    )


def folder_page(
    token: str,
    root_name: str,
    trail: list[Folder],
    folders: list[Folder],
    files: list[File],
    shared_root: uuid.UUID,
) -> str:
    crumbs = []
    for i, folder in enumerate(trail):
        label = _e(folder.name)
        if i == len(trail) - 1:
            crumbs.append(f"<strong>{label}</strong>")
        else:
            query = "" if folder.id == shared_root else f"?folder={folder.id}"
            crumbs.append(f'<a href="/s/{_e(token)}{query}">{label}</a>')
    rows = []
    for folder in folders:
        rows.append(
            f'<li><span class="grow">[+] <a href="/s/{_e(token)}?folder={folder.id}">'
            f"{_e(folder.name)}</a></span></li>"
        )
    for file in files:
        mime = (file.mime_type or "").lower()
        thumb = ""
        if mime.startswith(("image/", "video/")):
            thumb = (
                f'<img class="thumb" loading="lazy" alt="" '
                f'src="/s/{_e(token)}/file/{file.id}/thumbnail">'
            )
        rows.append(
            f'<li>{thumb}<span class="grow"><a href="/s/{_e(token)}/file/{file.id}/open">'
            f'{_e(file.name)}</a><br><span class="muted">{_size(file.size)}</span></span>'
            f'<a class="btn" href="/s/{_e(token)}/file/{file.id}">[ DOWNLOAD ]</a></li>'
        )
    listing = (
        "<ul>" + "".join(rows) + "</ul>" if rows else '<p class="muted">This folder is empty.</p>'
    )
    return page(
        f"<h1>CHOUD</h1><p class=\"muted\">{' / '.join(crumbs)}</p><hr>{listing}",
        root_name,
    )
