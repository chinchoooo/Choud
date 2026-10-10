"""Shared HTTP handling for the `base_version_id` precondition (sync clients).

A client that last saw a file at version V sends `base_version_id=V` with its
upload or delete. The server applies the change only if V is still the
current version; otherwise someone else got there first and the answer is a
`409` whose body says exactly what is current, so the client can keep both
sides' data (typically as a conflict copy) instead of overwriting.

`base_version_id=none` means "I believe nothing exists at this path yet" - the
create-only form of the same check. The parsing itself lives in
`version_service.parse_base_version`; this module only maps it to HTTP.
"""

import uuid

from fastapi import HTTPException

from app.services import version_service
from app.services.errors import ConflictError, ValidationError, VersionConflictError


def parse_base_version(raw: str | None) -> tuple[uuid.UUID | None, bool]:
    """`version_service.parse_base_version`, with a bad value reported as a 422."""
    try:
        return version_service.parse_base_version(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def conflict_http(exc: ConflictError) -> HTTPException:
    """409 for any ConflictError; version conflicts get a structured body."""
    if isinstance(exc, VersionConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "version_conflict",
                "message": str(exc),
                "file_id": str(exc.file_id) if exc.file_id else None,
                "current_version_id": (
                    str(exc.current_version_id) if exc.current_version_id else None
                ),
            },
        )
    return HTTPException(status_code=409, detail=str(exc))
