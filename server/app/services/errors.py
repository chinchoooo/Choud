"""Domain exceptions shared by the service layer.

These used to live in `file_service`. They moved here so that
`version_service` (which `file_service` calls on every upload) and
`file_service` can both raise them without importing each other in a
cycle. `file_service` still re-exports every name, so existing
`file_service.NotFoundError` references keep working and refer to the very
same class objects.
"""


class NotFoundError(Exception):
    """The requested file/folder doesn't exist, isn't owned by this user, or is deleted."""


class ConflictError(Exception):
    """The operation would violate a business rule (duplicate name, cycle, non-empty folder)."""


class ValidationError(Exception):
    """The request data is well-formed JSON/multipart but semantically invalid."""


class StorageError(Exception):
    """The storage engine couldn't complete the request (unreachable, object missing/corrupted)."""
