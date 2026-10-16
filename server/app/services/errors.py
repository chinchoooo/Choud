"""Domain exceptions shared by the service layer.

These used to live in `file_service`. They moved here so that
`version_service` (which `file_service` calls on every upload) and
`file_service` can both raise them without importing each other in a
cycle. `file_service` still re-exports every name, so existing
`file_service.NotFoundError` references keep working and refer to the very
same class objects.
"""

import uuid


class NotFoundError(Exception):
    """The requested file/folder doesn't exist, isn't owned by this user, or is deleted."""


class ConflictError(Exception):
    """The operation would violate a business rule (duplicate name, cycle, non-empty folder)."""


class VersionConflictError(ConflictError):
    """A write was based on a version of the file that is no longer current.

    Raised for an upload or delete that carried a `base_version_id` (or "this
    path must not exist yet") precondition which no longer holds, i.e. someone
    else changed the file in the meantime. The carried ids let a sync client
    decide what to do (typically: keep the other side's version and save its
    own as a conflict copy) without a second round trip.
    """

    def __init__(
        self,
        message: str,
        *,
        file_id: uuid.UUID | None = None,
        current_version_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.file_id = file_id
        self.current_version_id = current_version_id


class ValidationError(Exception):
    """The request data is well-formed JSON/multipart but semantically invalid."""


class StorageError(Exception):
    """The storage engine couldn't complete the request (unreachable, object missing/corrupted)."""


class QuotaError(Exception):
    """The upload would push the user past their storage quota."""


class PayloadTooLargeError(Exception):
    """A single request body is larger than the server accepts for that endpoint."""
